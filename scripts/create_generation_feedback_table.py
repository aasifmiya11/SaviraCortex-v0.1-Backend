"""Idempotently create the PostgreSQL RAG evaluation dataset table."""

from app.core.database import create_generation_feedback_table


if __name__ == "__main__":
    create_generation_feedback_table()
    print("generation_feedback table is ready.")
