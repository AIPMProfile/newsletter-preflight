#!/usr/bin/env python3
"""Entry point so `python cli.py audit <file.html>` works from a clean checkout.

The same interface installs as the `preflight` console script via pyproject.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from preflight.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
