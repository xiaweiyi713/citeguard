"""Install the bundled CiteGuard agent skill into supported clients."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sysconfig
from typing import Mapping, Optional


SKILL_NAME = "citeguard-verify"
CLIENT_SKILL_DIRS = {
    "codex": ".codex/skills",
    "claude": ".claude/skills",
    "cursor": ".cursor/skills",
}


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
        return Path(destination).expanduser().resolve()
    if client not in CLIENT_SKILL_DIRS:
        raise ValueError(f"Unsupported skill client {client!r}.")
    if scope not in {"user", "project"}:
        raise ValueError(f"Unsupported skill scope {scope!r}.")

    active_env = os.environ if env is None else env
    if scope == "project":
        root = Path(project_dir).expanduser() if project_dir else Path.cwd()
        return (root / CLIENT_SKILL_DIRS[client] / SKILL_NAME).resolve()

    if client == "codex" and str(active_env.get("CODEX_HOME", "")).strip():
        return (Path(str(active_env["CODEX_HOME"])).expanduser() / "skills" / SKILL_NAME).resolve()
    return (Path.home() / CLIENT_SKILL_DIRS[client] / SKILL_NAME).resolve()


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
    target = skill_destination(
        client,
        scope,
        destination=destination,
        project_dir=project_dir,
        env=env,
    )
    if target.exists() and _tree_digest(target) == _tree_digest(source):
        return _report(client, scope, source, target, installed=False, unchanged=True, overwritten=False)
    if target.exists() and not force:
        raise FileExistsError(
            f"Skill destination already exists and differs from the bundled skill: {target}. "
            "Use --force to replace only this skill directory."
        )

    overwritten = target.exists()
    if overwritten:
        if not target.is_dir() or target.is_symlink():
            raise FileExistsError(f"Refusing to replace non-directory skill destination: {target}")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return _report(client, scope, source, target, installed=True, unchanged=False, overwritten=overwritten)


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
    return {
        "ok": True,
        "skill": SKILL_NAME,
        "client": client,
        "scope": scope,
        "source": str(source),
        "destination": str(target),
        "installed": installed,
        "unchanged": unchanged,
        "overwritten": overwritten,
        "next_action": "restart_client_or_open_new_task",
    }


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
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
