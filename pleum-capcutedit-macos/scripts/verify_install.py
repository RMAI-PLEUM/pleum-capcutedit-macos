#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

raise SystemExit(subprocess.call([
    sys.executable, str(ROOT / "scripts/doctor.py"), "--run-tests"
]))
