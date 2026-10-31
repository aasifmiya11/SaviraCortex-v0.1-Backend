"""BM25 index management CLI.

Run from project root:
    python scripts/bm25.py list
    python scripts/bm25.py count
    python scripts/bm25.py show --document-id <ID>
    python scripts/bm25.py delete-id <ID>
    python scripts/bm25.py delete-source organized.pdf
    python scripts/bm25.py wipe --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.vector_stores.bm25 import bm25_client


def _read_rows(document_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT chunk_id, document_id, chunk_index, page_content, metadata
        FROM bm25_documents
    """
    params: tuple[Any, ...] = ()
    if document_id is not None:
        sql += " WHERE document_id = ?"
        params = (document_id,)
    sql += " ORDER BY document_id, chunk_index"

    # Use the same SQLite file as the BM25 vector-store singleton.
    with bm25_client._get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    output = []
    for row in rows:
        try:
            metadata = json.loads(row[4]) if row[4] else {}
        except (TypeError, json.JSONDecodeError):
            metadata = {}

        output.append({
            "chunk_id": row[0],
            "document_id": row[1],
            "chunk_index": row[2],
            "page_content": row[3],
            "metadata": metadata,
        })
    return output


def list_chunks(
    document_id: str | None = None,
    source: str | None = None,
    content_limit: int = 500,
) -> int:
    rows = _read_rows(document_id=document_id)
    if source is not None:
        rows = [r for r in rows if r["metadata"].get("source") == source]

    print(f"BM25 chunks found: {len(rows)}")
    for row in rows:
        content = row["page_content"]
        print("\n" + "=" * 90)
        print(f"Chunk ID:    {row['chunk_id']}")
        print(f"Document ID: {row['document_id']}")
        print(f"Chunk index: {row['chunk_index']}")
        print(f"Source:      {row['metadata'].get('source')}")
        print(f"Page:        {row['metadata'].get('page')}")
        print(f"Metadata:    {json.dumps(row['metadata'], ensure_ascii=False, default=str)}")
        print(f"Content:\n{content[:content_limit]}")
        if len(content) > content_limit:
            print(f"... [{len(content) - content_limit} more characters]")
    return len(rows)


def count_chunks() -> int:
    count = bm25_client.count()
    print(f"BM25 indexed chunks: {count}")
    return count


def delete_by_document_id(document_id: str) -> int:
    deleted = bm25_client.delete_document(document_id)
    print(f"Deleted {deleted} BM25 chunks for document_id={document_id}")
    return deleted


def delete_by_source(source: str) -> int:
    rows = _read_rows()
    matching = [r for r in rows if r["metadata"].get("source") == source]

    document_ids = {
        r["document_id"] for r in matching if r["document_id"] is not None
    }
    deleted = sum(
        bm25_client.delete_document(doc_id) for doc_id in document_ids
    )

    orphan_ids = [r["chunk_id"] for r in matching if r["document_id"] is None]
    if orphan_ids:
        placeholders = ",".join("?" for _ in orphan_ids)
        with bm25_client._get_connection() as conn:
            cursor = conn.execute(
                f"DELETE FROM bm25_documents WHERE chunk_id IN ({placeholders})",
                orphan_ids,
            )
            deleted += cursor.rowcount

    print(f"Deleted {deleted} BM25 chunks for source={source!r}")
    return deleted


def wipe_all(confirm: bool) -> None:
    if not confirm:
        raise SystemExit("Wipe cancelled. Pass --confirm to delete the entire BM25 corpus.")
    bm25_client.clear()
    print(f"BM25 corpus wiped. Remaining chunks: {bm25_client.count()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and manage the BM25 index.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--document-id")
    list_parser.add_argument("--source")
    list_parser.add_argument("--content-limit", type=int, default=500)

    sub.add_parser("count")

    show_parser = sub.add_parser("show")
    show_parser.add_argument("--document-id", required=True)
    show_parser.add_argument("--content-limit", type=int, default=2000)

    delete_id = sub.add_parser("delete-id")
    delete_id.add_argument("document_id")

    delete_source = sub.add_parser("delete-source")
    delete_source.add_argument("source")

    wipe = sub.add_parser("wipe")
    wipe.add_argument("--confirm", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "list":
        list_chunks(args.document_id, args.source, args.content_limit)
    elif args.command == "count":
        count_chunks()
    elif args.command == "show":
        list_chunks(document_id=args.document_id, content_limit=args.content_limit)
    elif args.command == "delete-id":
        delete_by_document_id(args.document_id)
    elif args.command == "delete-source":
        delete_by_source(args.source)
    elif args.command == "wipe":
        wipe_all(args.confirm)


if __name__ == "__main__":
    main()
