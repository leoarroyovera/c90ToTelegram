#!/usr/bin/env python3
"""Punto de entrada. Carga .env y ejecuta el CLI."""
import os
import sys
from pathlib import Path

env = Path(__file__).parent / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(Path(__file__).parent))
from c90.main import main

main()
