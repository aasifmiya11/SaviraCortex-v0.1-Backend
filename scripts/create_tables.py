import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import create_tables, close_database


if __name__ == "__main__":
    try:
        create_tables()
    finally:
        close_database()
