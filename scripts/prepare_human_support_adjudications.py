#!/usr/bin/env python3
"""Prepare a private, content-bound third-review packet for candidate disputes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.human_adjudication import build_candidate_adjudication_packet
from citeguard.benchmark.human_candidates import HumanSupportCandidateError


def _read_object(path: str) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HumanSupportCandidateError(f"{path} must contain a JSON object")
    return value


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare third-party adjudication of disputed real-source support cases.")
    parser.add_argument("--candidates", required=True, help="Original unlabeled candidate catalog.")
    parser.add_argument("--packet", action="append", required=True, help="Completed intact reviewer packet; repeat per reviewer.")
    parser.add_argument("--output", required=True, help="New private adjudication packet path.")
    args = parser.parse_args(argv)
    try:
        output = Path(args.output).expanduser()
        if output.resolve() in {Path(path).resolve() for path in [args.candidates, *args.packet]}:
            raise HumanSupportCandidateError("adjudication output must not overwrite an input")
        packet = build_candidate_adjudication_packet(
            _read_object(args.candidates), [_read_object(path) for path in args.packet]
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
            json.dump(packet, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({
            "ok": True,
            "output": str(output),
            "case_count": packet["case_count"],
            "packet_digest": packet["packet_digest"],
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, HumanSupportCandidateError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
