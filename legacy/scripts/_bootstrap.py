"""Helpers for running legacy prototype scripts from a source checkout.

Mirrors scripts/_bootstrap.py but resolves the repository root from
legacy/scripts/ (two levels up) so `python3 legacy/scripts/<name>.py`
can import both `citeguard.*` and `legacy.*` without installation.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path


def ensure_project_root() -> None:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    warnings.filterwarnings(
        "ignore",
        message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
    )

    try:
        from urllib3.exceptions import NotOpenSSLWarning

        warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
    except Exception:
        pass

    project_root = Path(__file__).resolve().parents[2]
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
