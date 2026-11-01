
import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi
from langchain_core.documents import Document


# Project root: Voice-AI/
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "bm25_index.sqlite3"


class BM25VectorStoreClient:

    def __init__(self, db_path: Optional[str] = None):

        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        self.documents: list[Document] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25_index: Optional[BM25Okapi] = None

        self._initialize_database()
        self._load_index()

    # --------------------------------------------------
    # DATABASE
    # --------------------------------------------------

    def _get_connection(self):
        return sqlite3.connect(str(self.db_path))

    def _initialize_database(self):

        with self._get_connection() as conn:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS bm25_documents (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT,
                    document_version_id TEXT,
                    chunk_index INTEGER,
                    page_content TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)

            # Migrate existing databases without deleting data.
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(bm25_documents)"
                ).fetchall()
            }

            if "document_version_id" not in columns:
                conn.execute("""
                    ALTER TABLE bm25_documents
                    ADD COLUMN document_version_id TEXT
                """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bm25_document_id
                ON bm25_documents(document_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bm25_document_version_id
                ON bm25_documents(document_version_id)
            """)

    # --------------------------------------------------
    # TOKENIZATION
    # --------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:

        return re.findall(r"\b\w+\b", text.lower())

    # --------------------------------------------------
    # CHUNK ID
    # --------------------------------------------------

    @staticmethod
    def _get_chunk_id(document: Document) -> str:

        metadata = document.metadata or {}

        document_version_id = metadata.get("document_version_id")
        document_id = metadata.get("document_id")
        chunk_index = metadata.get("chunk_index")

        # Version-aware identity.
        if document_version_id is not None and chunk_index is not None:

            identity = f"{document_version_id}:{chunk_index}"

        # Backward compatibility for existing non-versioned ingestion.
        elif document_id is not None and chunk_index is not None:

            identity = f"{document_id}:{chunk_index}"

        else:

            identity = (
                f"{metadata.get('source', '')}:"
                f"{metadata.get('page', '')}:"
                f"{document.page_content}"
            )

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    # --------------------------------------------------
    # INGEST DOCUMENTS / CREATE BM25 INDEX
    # --------------------------------------------------

    def add_documents(self, documents: list[Document]) -> list[str]:

        if not documents:
            return []

        chunk_ids = []

        with self._lock:

            with self._get_connection() as conn:

                for document in documents:

                    metadata = document.metadata or {}
                    chunk_id = self._get_chunk_id(document)

                    conn.execute("""
                        INSERT INTO bm25_documents (
                            chunk_id,
                            document_id,
                            document_version_id,
                            chunk_index,
                            page_content,
                            metadata
                        )
                        VALUES (?, ?, ?, ?, ?, ?)

                        ON CONFLICT(chunk_id) DO UPDATE SET
                            document_id = excluded.document_id,
                            document_version_id = excluded.document_version_id,
                            chunk_index = excluded.chunk_index,
                            page_content = excluded.page_content,
                            metadata = excluded.metadata
                    """, (
                        chunk_id,
                        metadata.get("document_id"),
                        metadata.get("document_version_id"),
                        metadata.get("chunk_index"),
                        document.page_content,
                        json.dumps(metadata, default=str)
                    ))

                    chunk_ids.append(chunk_id)

            # Rebuild the in-memory BM25 index.
            self._load_index()

        return chunk_ids

    # --------------------------------------------------
    # LOAD / BUILD INDEX
    # --------------------------------------------------

    def _load_index(self):

        with self._lock:

            with self._get_connection() as conn:

                rows = conn.execute("""
                    SELECT page_content, metadata
                    FROM bm25_documents
                """).fetchall()

            self.documents = []
            self.tokenized_corpus = []

            for page_content, metadata_json in rows:

                tokens = self._tokenize(page_content)

                if not tokens:
                    continue

                document = Document(
                    page_content=page_content,
                    metadata=json.loads(metadata_json)
                )

                self.documents.append(document)
                self.tokenized_corpus.append(tokens)

            self.bm25_index = (
                BM25Okapi(self.tokenized_corpus)
                if self.tokenized_corpus
                else None
            )

    # --------------------------------------------------
    # SEARCH
    # --------------------------------------------------

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[tuple[Document, float]]:

        if k <= 0:
            return []

        query_tokens = self._tokenize(query)

        if not query_tokens:
            return []

        with self._lock:

            if self.bm25_index is None:
                return []

            scores = self.bm25_index.get_scores(query_tokens)

            results = []

            for index, score in enumerate(scores):

                document = self.documents[index]
                metadata = document.metadata

                if document_id is not None:
                    if metadata.get("document_id") != document_id:
                        continue

                if user_id is not None:
                    if metadata.get("user_id") != user_id:
                        continue

                results.append((document, float(score)))

            results.sort(
                key=lambda item: item[1],
                reverse=True
            )

            return results[:k]

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[Document]:

        results = self.similarity_search_with_score(
            query=query,
            k=k,
            document_id=document_id,
            user_id=user_id
        )

        return [document for document, _ in results]

    # --------------------------------------------------
    # DELETE DOCUMENT
    # --------------------------------------------------

    def delete_document(self, document_id: str) -> int:

        with self._lock:

            with self._get_connection() as conn:

                cursor = conn.execute("""
                    DELETE FROM bm25_documents
                    WHERE document_id = ?
                """, (document_id,))

                deleted_count = cursor.rowcount

            self._load_index()

        return deleted_count

    # --------------------------------------------------
    # DELETE DOCUMENT VERSION
    # --------------------------------------------------

    def delete_version(self, document_version_id: str) -> int:
        """
        Delete all chunks belonging to a specific document version.

        Other versions of the same logical document remain untouched.
        """

        with self._lock:

            with self._get_connection() as conn:

                cursor = conn.execute("""
                    DELETE FROM bm25_documents
                    WHERE document_version_id = ?
                """, (document_version_id,))

                deleted_count = cursor.rowcount

            self._load_index()

        return deleted_count

    # --------------------------------------------------
    # DELETE SPECIFIC CHUNKS
    # --------------------------------------------------

    def delete_chunks(self, chunk_ids: list[str]) -> int:
        """
        Delete specific chunks using their BM25 chunk IDs.

        Uses batches to avoid SQLite parameter-count limits.
        """

        if not chunk_ids:
            return 0

        if not isinstance(chunk_ids, list):
            raise TypeError("chunk_ids must be a list.")

        if any(not isinstance(chunk_id, str) for chunk_id in chunk_ids):
            raise TypeError("Every chunk ID must be a string.")

        # Remove duplicate IDs while preserving order.
        chunk_ids = list(dict.fromkeys(chunk_ids))

        deleted_count = 0
        batch_size = 900

        with self._lock:

            with self._get_connection() as conn:

                for start in range(0, len(chunk_ids), batch_size):

                    batch = chunk_ids[start:start + batch_size]

                    placeholders = ",".join(
                        "?" for _ in batch
                    )

                    cursor = conn.execute(
                        f"""
                        DELETE FROM bm25_documents
                        WHERE chunk_id IN ({placeholders})
                        """,
                        batch,
                    )

                    deleted_count += cursor.rowcount

            self._load_index()

        return deleted_count

    # --------------------------------------------------
    # INDEX INFORMATION
    # --------------------------------------------------

    def count(self) -> int:

        with self._get_connection() as conn:

            result = conn.execute("""
                SELECT COUNT(*)
                FROM bm25_documents
            """).fetchone()

        return result[0]

    def clear(self):

        with self._lock:

            with self._get_connection() as conn:
                conn.execute("DELETE FROM bm25_documents")

            self._load_index()


# Singleton instance
bm25_client = BM25VectorStoreClient()
