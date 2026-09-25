"""Install, inspect, and safely upgrade the bundled CiteGuard agent skill."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sysconfig
import tempfile
from typing import Mapping, Optional, Union


SKILL_NAME = "citeguard-verify"
CLIENT_SKILL_DIRS = {
    "codex": ".codex/skills",
    "claude": ".claude/skills",
    "cursor": ".cursor/skills",
}
REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/tool-payloads.md",
    "references/result-policy.md",
)


def bundled_skill_path(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return the packaged skill directory for a wheel or source checkout."""

    active_env = os.environ if env is None else env
    override = str(active_env.get("CITEGUARD_SKILL_BUNDLE", "")).strip()
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend(
        [
            Path(sysconfig.get_path("data")) / "share" / "citationguard" / "skills" / SKILL_NAME,
            Path(__file__).resolve().parents[1] / "skills" / SKILL_NAME,
        ]
    )
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file() and (candidate / "agents" / "openai.yaml").is_file():
            return candidate.resolve()
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Bundled {SKILL_NAME} skill was not found. Searched: {searched}")


def skill_destination(
    client: str,
    scope: str,
    *,
    destination: str = "",
    project_dir: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Resolve a client skill destination without creating it."""

    if destination:
        return _absolute_path(Path(destination).expanduser())
    if client not in CLIENT_SKILL_DIRS:
        raise ValueError(f"Unsupported skill client {client!r}.")
    if scope not in {"user", "project"}:
        raise ValueError(f"Unsupported skill scope {scope!r}.")

    active_env = os.environ if env is None else env
    if scope == "project":
        root = Path(project_dir).expanduser() if project_dir else Path.cwd()
        return _absolute_path(root / CLIENT_SKILL_DIRS[client] / SKILL_NAME)

    if client == "codex" and str(active_env.get("CODEX_HOME", "")).strip():
        return _absolute_path(Path(str(active_env["CODEX_HOME"])).expanduser() / "skills" / SKILL_NAME)
    return _absolute_path(Path.home() / CLIENT_SKILL_DIRS[client] / SKILL_NAME)


def skill_status(
    client: str,
    scope: str = "user",
    *,
    destination: str = "",
    project_dir: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Describe whether one installed skill is intact and matches this package."""

    source = bundled_skill_path(env)
    source_integrity = _skill_integrity(source)
    if not source_integrity["valid"]:
        raise RuntimeError(f"Bundled {SKILL_NAME} skill is invalid: {', '.join(source_integrity['errors'])}")
    target = skill_destination(client, scope, destination=destination, project_dir=project_dir, env=env)
    installed_integrity = _skill_integrity(target)
    source_digest = _tree_digest(source)
    installed_digest = _tree_digest(target) if installed_integrity["valid"] else ""

    if not installed_integrity["exists"]:
        state = "not_installed"
        next_action = "install_skill"
    elif not installed_integrity["valid"]:
        state = "invalid"
        next_action = "repair_or_reinstall_skill"
    elif installed_digest == source_digest:
        state = "current"
        next_action = "restart_client_or_open_new_task"
    else:
        state = "modified_or_outdated"
        next_action = "review_then_upgrade_with_force"

    return {
        "ok": True,
        "operation": "status",
        "skill": SKILL_NAME,
        "client": client,
        "scope": scope,
        "source": str(source),
        "destination": str(target),
        "state": state,
        "installed": installed_integrity["exists"],
        "valid": installed_integrity["valid"],
        "matches_bundled": state == "current",
        "source_digest": _digest_label(source_digest),
        "installed_digest": _digest_label(installed_digest),
        "missing_required_files": installed_integrity["missing_required_files"],
        "integrity_errors": installed_integrity["errors"],
        "next_action": next_action,
    }


def check_skill(
    client: str,
    scope: str = "user",
    *,
    destination: str = "",
    project_dir: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Run the post-install self-check; only an exact bundle match passes."""

    report = skill_status(
        client,
        scope,
        destination=destination,
        project_dir=project_dir,
        env=env,
    )
    report.update(
        {
            "operation": "check",
            "ok": report["state"] == "current",
            "checks": ["required_files", "skill_frontmatter", "bundle_digest"],
        }
    )
    return report


def skill_digest(path: Union[str, Path]) -> str:
    """Return the bundled-tree-compatible digest for one intact skill directory."""

    root = Path(path).expanduser()
    integrity = _skill_integrity(root)
    if not integrity["exists"]:
        raise FileNotFoundError(f"Skill directory does not exist: {root}")
    if not integrity["valid"]:
        details = ", ".join(integrity["errors"] + integrity["missing_required_files"])
        raise ValueError(f"Skill directory is not an intact {SKILL_NAME} bundle: {details}")
    digest = _tree_digest(root)
    if not digest:
        raise ValueError(f"Could not calculate a digest for skill directory: {root}")
    return _digest_label(digest) or ""


def install_skill(
    client: str,
    scope: str = "user",
    *,
    destination: str = "",
    project_dir: str = "",
    force: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Install the bundled skill and return a stable machine-readable report."""

    source = bundled_skill_path(env)
    source_integrity = _skill_integrity(source)
    if not source_integrity["valid"]:
        raise RuntimeError(f"Bundled {SKILL_NAME} skill is invalid: {', '.join(source_integrity['errors'])}")
    target = skill_destination(client, scope, destination=destination, project_dir=project_dir, env=env)
    target_exists = target.exists() or target.is_symlink()
    target_integrity = _skill_integrity(target)
    if target_exists and target_integrity["valid"] and _tree_digest(target) == _tree_digest(source):
        return _report(client, scope, source, target, installed=False, unchanged=True, overwritten=False)
    if target_exists and not force:
        raise FileExistsError(
            f"Skill destination already exists and differs from the bundled skill: {target}. "
            "Use --force to replace only an identified CiteGuard skill directory."
        )

    overwritten = target_exists
    if overwritten:
        _replace_skill_tree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return _report(client, scope, source, target, installed=True, unchanged=False, overwritten=overwritten)


def upgrade_skill(
    client: str,
    scope: str = "user",
    *,
    destination: str = "",
    project_dir: str = "",
    force: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Upgrade only an existing skill, requiring consent for a differing tree."""

    status = skill_status(
        client,
        scope,
        destination=destination,
        project_dir=project_dir,
        env=env,
    )
    if status["state"] == "current":
        return {**status, "operation": "upgrade", "upgraded": False, "requires_force": False}
    if status["state"] == "not_installed":
        return {
            **status,
            "operation": "upgrade",
            "ok": False,
            "upgraded": False,
            "requires_force": False,
            "next_action": "install_skill",
        }
    if not force:
        return {
            **status,
            "operation": "upgrade",
            "ok": False,
            "upgraded": False,
            "requires_force": True,
            "next_action": "review_then_upgrade_with_force",
        }
    report = install_skill(
        client,
        scope,
        destination=destination,
        project_dir=project_dir,
        force=True,
        env=env,
    )
    return {**report, "operation": "upgrade", "upgraded": report["installed"], "requires_force": False}


def _report(
    client: str,
    scope: str,
    source: Path,
    target: Path,
    *,
    installed: bool,
    unchanged: bool,
    overwritten: bool,
) -> dict:
    source_digest = _tree_digest(source)
    installed_digest = _tree_digest(target)
    return {
        "ok": True,
        "operation": "install",
        "skill": SKILL_NAME,
        "client": client,
        "scope": scope,
        "source": str(source),
        "destination": str(target),
        "installed": installed,
        "unchanged": unchanged,
        "overwritten": overwritten,
        "state": "current",
        "source_digest": _digest_label(source_digest),
        "installed_digest": _digest_label(installed_digest),
        "next_action": "run_skill_check",
    }


def _replace_skill_tree(source: Path, target: Path) -> None:
    """Atomically replace a known CiteGuard skill after an explicit force flag."""

    if not target.is_dir() or target.is_symlink() or not _is_citeguard_skill(target / "SKILL.md"):
        raise FileExistsError(
            f"Refusing to replace a destination that is not an identified {SKILL_NAME} skill directory: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=f".{target.name}.citeguard-", dir=str(target.parent)))
    staged = stage_root / "replacement"
    backup = stage_root / "previous"
    try:
        shutil.copytree(source, staged)
        target.rename(backup)
        try:
            staged.rename(target)
        except Exception:
            backup.rename(target)
            raise
        shutil.rmtree(backup)
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root, ignore_errors=True)


def _skill_integrity(root: Path) -> dict:
    """Inspect an on-disk skill without following a root symlink."""

    if root.is_symlink():
        return {
            "exists": True,
            "valid": False,
            "missing_required_files": [],
            "errors": ["skill_root_must_not_be_symlink"],
        }
    if not root.exists():
        return {
            "exists": False,
            "valid": False,
            "missing_required_files": list(REQUIRED_SKILL_FILES),
            "errors": [],
        }
    if not root.is_dir():
        return {
            "exists": True,
            "valid": False,
            "missing_required_files": [],
            "errors": ["skill_root_must_be_directory"],
        }
    missing = [relative for relative in REQUIRED_SKILL_FILES if not (root / relative).is_file()]
    errors = []
    if any(path.is_symlink() for path in root.rglob("*")):
        errors.append("skill_bundle_must_not_contain_symlinks")
    if not missing and not _is_citeguard_skill(root / "SKILL.md"):
        errors.append("skill_frontmatter_name_mismatch")
    return {
        "exists": True,
        "valid": not missing and not errors,
        "missing_required_files": missing,
        "errors": errors,
    }


def _is_citeguard_skill(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not text.startswith("---\n"):
        return False
    frontmatter = text[4:].split("\n---\n", 1)[0]
    return any(line.strip() == f"name: {SKILL_NAME}" for line in frontmatter.splitlines())


def _tree_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        return ""
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _digest_label(value: str) -> Optional[str]:
    return "sha256:" + value if value else None


def _absolute_path(path: Path) -> Path:
    """Make a path absolute without resolving a possible skill-root symlink."""

    expanded = Path(os.path.abspath(str(path)))
    return expanded.parent.resolve(strict=False) / expanded.name
