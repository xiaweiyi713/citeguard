"""Optional, local-only, privacy-preserving runtime event metrics."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Mapping, Optional, Sequence


METRICS_SCHEMA_VERSION = 1
MAX_METRICS_FILE_BYTES = 10 * 1024 * 1024
_ALLOWED_EVENTS = {
    "cli:status",
    "cli:skill",
    "cli:skill:check",
    "cli:skill:install",
    "cli:skill:status",
    "cli:skill:upgrade",
    "cli:models",
    "cli:cache",
    "cli:verify",
    "cli:audit",
    "cli:audit-document",
    "cli:extract",
    "cli:support",
    "cli:support-set",
    "cli:support-audit",
    "cli:counterevidence",
    "cli:invalid_command",
    "mcp:citeguard_status_tool",
    "mcp:verify_citation_tool",
    "mcp:audit_citations_tool",
    "mcp:audit_document_tool",
    "mcp:check_claim_support_tool",
    "mcp:check_claim_support_set_tool",
    "mcp:search_counterevidence_tool",
    "mcp:audit_claim_support_tool",
}
_OUTCOMES = {"success", "failure"}


def metrics_status(env: Optional[Mapping[str, str]] = None) -> dict:
    """Return non-sensitive local metrics configuration without exposing its path."""

    configured = bool(metrics_path(env))
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "enabled": configured,
        "transport": "local_jsonl" if configured else "disabled",
        "network_transmission": False,
        "path_exposed": False,
        "recorded_fields": ["schema_version", "event", "outcome", "duration_bucket", "occurred_at"],
        "next_action": "continue" if configured else "configure_local_metrics_path",
    }


def metrics_path(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the explicitly configured local metrics destination, or an empty string."""

    active_env = os.environ if env is None else env
    return str(active_env.get("CITEGUARD_METRICS_PATH", "")).strip()


def record_runtime_metric(
    event: str,
    outcome: str,
    elapsed_seconds: float,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Append one aggregate event only when the user explicitly configured a path.

    Metrics never include request arguments, claims, citation metadata, evidence,
    local input paths, hostnames, user identity, or source responses. Failures are
    intentionally non-fatal so metrics cannot alter verification behavior.
    """

    destination = metrics_path(env)
    if not destination or event not in _ALLOWED_EVENTS or outcome not in _OUTCOMES:
        return False
    payload = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "event": event,
        "outcome": outcome,
        "duration_bucket": _duration_bucket(elapsed_seconds),
        "occurred_at": _utc_now_iso(),
    }
    serialized = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        path = Path(destination).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = _open_metrics_destination(path)
        if descriptor is None:
            return False
        try:
            if os.fstat(descriptor).st_size + len(serialized) > MAX_METRICS_FILE_BYTES:
                return False
            _write_all(descriptor, serialized)
            return True
        finally:
            os.close(descriptor)
    except OSError:
        return False


def _open_metrics_destination(path: Path) -> Optional[int]:
    """Open only a regular, non-symlink metrics file with private POSIX bits."""

    if path.is_symlink():
        return None
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            return None
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        return descriptor
    except OSError:
        os.close(descriptor)
        return None


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write the complete encoded event without relying on buffered text I/O."""

    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("could not write runtime metrics event")
        remaining = remaining[written:]


def cli_metric_event(argv: Optional[Sequence[str]]) -> str:
    """Map CLI tokens to an allowlisted event without retaining any input values."""

    values = list(argv or [])
    commands = {
        "status",
        "skill",
        "models",
        "cache",
        "verify",
        "audit",
        "audit-document",
        "extract",
        "support",
        "support-set",
        "support-audit",
        "counterevidence",
    }
    command_index = next((index for index, value in enumerate(values) if value in commands), None)
    if command_index is None:
        return "cli:invalid_command"
    command = values[command_index]
    if command != "skill":
        return f"cli:{command}"
    skill_commands = {"install", "status", "check", "upgrade"}
    skill_command = next(
        (value for value in values[command_index + 1 :] if value in skill_commands),
        "",
    )
    return f"cli:skill:{skill_command}" if skill_command else "cli:skill"


def _duration_bucket(elapsed_seconds: float) -> str:
    try:
        elapsed = max(0.0, float(elapsed_seconds))
    except (TypeError, ValueError):
        return "unknown"
    if elapsed < 0.1:
        return "lt_100ms"
    if elapsed < 1.0:
        return "100ms_to_lt_1s"
    if elapsed < 10.0:
        return "1s_to_lt_10s"
    return "10s_or_more"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "MAX_METRICS_FILE_BYTES",
    "METRICS_SCHEMA_VERSION",
    "cli_metric_event",
    "metrics_path",
    "metrics_status",
    "record_runtime_metric",
]
