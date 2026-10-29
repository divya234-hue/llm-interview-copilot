import logging
from functools import lru_cache

from app.core.config import get_settings
from app.services.documents import split_chunks

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def _get_chroma_collection(path: str):
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("ChromaDB is unavailable; install backend/requirements.txt.") from exc
    client = chromadb.PersistentClient(path=path)
    return client.get_or_create_collection("interview_documents")


@lru_cache(maxsize=2)
def _get_embedder(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Sentence Transformers is unavailable; install backend/requirements.txt.") from exc
    return SentenceTransformer(model_name)


class LocalKnowledgeBase:
    def __init__(self) -> None:
        settings = get_settings()
        self.path = settings.chroma_path
        self.embedding_model = settings.embedding_model
        self._collection = None
        self._embedder = None

    def _get_collection(self):
        if self._collection is None:
            self._collection = _get_chroma_collection(self.path)
        return self._collection

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = _get_embedder(self.embedding_model)
        return self._embedder

    @staticmethod
    def content_hash(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def add_document(self, workspace_id: str, document_id: str, text: str, source: str) -> int:
        collection = self._get_collection()
        chunks = split_chunks(text)
        if not chunks:
            return 0
        embeddings = self._get_embedder().encode(chunks).tolist()
        ids = [f"{document_id}-{index}" for index in range(len(chunks))]
        collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=[
                {
                    "workspace_id": workspace_id,
                    "source": source,
                    "document_id": document_id,
                    "content_hash": self.content_hash(text),
                    "chunk": index,
                }
                for index in range(len(chunks))
            ],
        )
        return len(chunks)

    def delete_document(self, document_id: str) -> None:
        self._get_collection().delete(where={"document_id": document_id})

    def retrieve(self, query: str, workspace_id: str = "local", limit: int = 4) -> list[str]:
        collection = self._get_collection()
        where = {"workspace_id": workspace_id}
        count = collection.count()
        if count == 0:
            return []
        embedding = self._get_embedder().encode([query]).tolist()
        result = collection.query(query_embeddings=embedding, n_results=min(limit, count), where=where)
        return [text for text in (result.get("documents") or [[]])[0] if text]
