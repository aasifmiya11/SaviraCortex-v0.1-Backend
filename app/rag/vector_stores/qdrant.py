import sys
from pathlib import Path

# Add project root
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models
from langchain_core.documents import Document

from app.rag.embeddings.huggingface_embeddings import embedding_model
from app.core.config import settings


class QdrantVectorStoreClient:

    def __init__(self):
        self.collection_name = settings.QDRANT_COLLECTION_NAME

        # Connect to Qdrant
        self.client = QdrantClient(
            url=settings.QDRANT_API_ENDPOINT,
            api_key=settings.QDRANT_API_KEY
        )

        # Create collection if it does not exist
        self._create_collection_if_not_exists()

        # Initialize LangChain vector store
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=embedding_model
        )

    def _create_collection_if_not_exists(self):
        if not self.client.collection_exists(self.collection_name):

            embedding_dimension = len(
                embedding_model.embed_query("dimension check")
            )

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=embedding_dimension,
                    distance=models.Distance.COSINE
                )
            )

            print(
                f"Created Qdrant collection: {self.collection_name}"
            )
        else:
            print(
                f"Using existing Qdrant collection: {self.collection_name}"
            )

    def add_documents(self, documents: list[Document]):
        return self.vector_store.add_documents(documents)

    def similarity_search(self, query: str, k: int = 4):
        return self.vector_store.similarity_search(
            query=query,
            k=k
        )
        
    def similarity_search_with_score(self, query: str, k: int = 4, query_filter: models.Filter | None = None):
        return self.vector_store.similarity_search_with_score(
            query=query,
            k=k,
            query_filter=query_filter
        )

    def delete_collection(self):
        self.client.delete_collection(self.collection_name)
        print(f"Deleted collection: {self.collection_name}")


# Singleton instance
client = QdrantVectorStoreClient()


if __name__ == "__main__":

    documents = [
        Document(
            page_content="Hello world!",
            metadata={"source": "example1"}
        ),
        Document(
            page_content="This is a test.",
            metadata={"source": "example2"}
        )
    ]

    client.add_documents(documents)

    results = client.similarity_search("Hello", k=2)

    for result in results:
        print(result)
    # client.delete_collection()