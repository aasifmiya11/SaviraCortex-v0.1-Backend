"""Initialize all SaviraCortex PostgreSQL tables from the current SQLAlchemy models."""

from app.core.database import create_tables


if __name__ == "__main__":
    create_tables()
