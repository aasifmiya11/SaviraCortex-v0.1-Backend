"""Compatibility entry point; use scripts/database.py for schema reset."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database import reset_database
from app.core.database import engine


if __name__ == "__main__":
    try:
        reset_database()
    finally:
        engine.dispose()
