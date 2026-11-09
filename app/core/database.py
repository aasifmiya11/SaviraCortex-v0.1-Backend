
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


# =====================================================
# SQLAlchemy Base
# =====================================================

class Base(DeclarativeBase):
    pass


# =====================================================
# Database Configuration
# =====================================================

if not settings.AIVEN_POSTGRES_URI:
    raise ValueError(
        "AIVEN_POSTGRES_URI is missing from environment variables."
    )


engine = create_engine(
    settings.AIVEN_POSTGRES_URI,
)


# =====================================================
# Session Factory
# =====================================================

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


# =====================================================
# Database Session
# =====================================================

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Provides a database session to repositories.

    Rolls back on exceptions and always closes the session.
    Transaction commits are controlled by the calling service
    or repository.
    """

    db = SessionLocal()

    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =====================================================
# Database Initialization
# =====================================================

def create_tables() -> None:
    """
    Create all registered SQLAlchemy tables.

    Existing tables are not modified.
    """

    # Import models to register them with Base.metadata.
    from ..models import (
        Organization,
        User,
        OrganizationMembership,
        OrganizationInvitation,
        Document,
        DocumentVersion,
        DocumentIngestionSession,
    )
    Base.metadata.create_all(bind=engine)

    print("Database initialized successfully.")
    print("Registered tables:")

    for table_name in Base.metadata.tables:
        print(f"  - {table_name}")


# =====================================================
# Database Shutdown
# =====================================================

def close_database() -> None:
    """Dispose of the database connection pool."""

    engine.dispose()
    print("Database connection pool disposed.")


def create_generation_feedback_table() -> None:
    """Create only the RAG evaluation dataset table when it is missing."""
    from ..models import GenerationFeedback, Organization, User

    _ = (Organization, User)  # Register referenced tables in Base.metadata.
    GenerationFeedback.__table__.create(bind=engine, checkfirst=True)
