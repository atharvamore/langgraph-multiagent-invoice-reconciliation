# vector_db/vector_service.py
import os
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

class VectorStorageService:
    def __init__(self, persistent_path: str = "database/chroma_db"):
        """Connect to persistent ChromaDB store with explicit semantic embedding function."""
        os.makedirs(persistent_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persistent_path)
        
        # Explicit embedding function using ONNX MiniLM
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # Create or fetch collection with cosine similarity
        self.collection = self.client.get_or_create_collection(
            name="invoice_line_items",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )

    def add_line_item(self, item_id: str, invoice_no: str, description: str, metadata: dict = None):
        """Store one invoice line-item description and its invoice metadata in ChromaDB."""
        meta = metadata or {}
        meta["invoice_no"] = invoice_no
        meta["description"] = description
        
        self.collection.add(
            documents=[description],
            metadatas=[meta],
            ids=[item_id]
        )

    def query_similar_items(self, query_text: str, limit: int = 3):
        """Return the closest semantic matches for a given line-item query."""
        results = self.collection.query(
            query_texts=[query_text],
            n_results=limit
        )
        return results
