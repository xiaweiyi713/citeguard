#!/usr/bin/env python3
"""Preview or stage curator-approved real-source support benchmark cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.human_candidates import HumanSupportCandidateError
from citeguard.benchmark.human_promotion import promote_human_support_candidates


def _read_object(path: str) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HumanSupportCandidateError(f"{path} must contain a JSON object")
    return value


def _publish_json_bundle(outputs: Sequence[Tuple[str, Dict[str, Any]]]) -> None:
    """Publish private files without partial content or overwriting an existing path."""

    staged: List[Tuple[Path, Path, int, str]] = []
    published: List[Tuple[Path, int, str]] = []
    try:
        for path, payload in outputs:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            temporary = Path(temporary_name)
            staged.append((target, temporary, os.fstat(descriptor).st_ino, digest))
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for target, temporary, inode, digest in staged:
            os.link(temporary, target)
            published.append((target, inode, digest))
    except (OSError, ValueError):
        for target, inode, digest in reversed(published):
            try:
                if target.lstat().st_ino == inode and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for _, temporary, _, _ in staged:
            temporary.unlink(missing_ok=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Stage independently agreed real-source cases after curator review.")
    parser.add_argument("--candidates", required=True, help="Original unlabeled candidate catalog, not merged output.")
    parser.add_argument("--packet", action="append", required=True, help="Completed intact packet; repeat per reviewer.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument("--label-sidecar", default="data/eval/support_eval_label_sidecar.json")
    parser.add_argument("--curator-id", required=True, help="Dataset reviewer ID, distinct from the annotators.")
    parser.add_argument("--adjudications", help="Completed third-party adjudication packet for reviewer disagreements.")
    parser.add_argument("--approve", action="store_true", help="Write proposed files after dataset review.")
    parser.add_argument("--dataset-output", help="New path for the proposed support evaluation dataset.")
    parser.add_argument("--sidecar-output", help="New path for the proposed label sidecar.")
    parser.add_argument("--report", help="Optional path for the preview/promotion report.")
    args = parser.parse_args(argv)
    try:
        if args.approve and (not args.dataset_output or not args.sidecar_output):
            raise HumanSupportCandidateError("--approve requires --dataset-output and --sidecar-output")
        input_paths = [args.candidates, *args.packet, args.dataset, args.label_sidecar]
        if args.adjudications:
            input_paths.append(args.adjudications)
        output_paths = [path for path in (args.dataset_output, args.sidecar_output, args.report) if path]
        resolved_inputs = {Path(path).resolve() for path in input_paths}
        resolved_outputs = [Path(path).resolve() for path in output_paths]
        if len(set(resolved_outputs)) != len(resolved_outputs) or any(path in resolved_inputs for path in resolved_outputs):
            raise HumanSupportCandidateError("output paths must be distinct and must not overwrite inputs")
        if args.approve and any(path.exists() for path in resolved_outputs):
            raise HumanSupportCandidateError("proposed output already exists; choose new paths")
        updated_dataset, updated_sidecar, report = promote_human_support_candidates(
            _read_object(args.candidates),
            [_read_object(path) for path in args.packet],
            _read_object(args.dataset),
            _read_object(args.label_sidecar),
            curator_id=args.curator_id,
            adjudications=_read_object(args.adjudications) if args.adjudications else None,
        )
        report["approved_for_staging"] = bool(args.approve)
        outputs = []
        if args.approve:
            if not report["promoted_count"]:
                raise HumanSupportCandidateError("no eligible cases to stage")
            outputs.extend([
                (args.dataset_output, updated_dataset),
                (args.sidecar_output, updated_sidecar),
            ])
        if args.report:
            outputs.append((args.report, report))
        _publish_json_bundle(outputs)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, HumanSupportCandidateError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
