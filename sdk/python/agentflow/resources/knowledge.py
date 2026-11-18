from __future__ import annotations

from typing import Any


class KnowledgeResource:
    def __init__(self, client: AgentFlowClient) -> None:
        self._c = client

    def list(self) -> Any:
        return self._c.request("GET", "/api/knowledge-bases")

    def get(self, kb_id: int) -> Any:
        return self._c.request("GET", f"/api/knowledge-bases/{kb_id}")

    def create(
        self,
        name: str,
        *,
        description: str = "",
        embedding_provider: str = "mock",
        embedding_model: str = "text-embedding-3-small",
        chunk_size: int = 600,
        chunk_overlap: int = 80,
    ) -> Any:
        payload = {
            "name": name,
            "description": description,
            "embeddingProvider": embedding_provider,
            "embeddingModel": embedding_model,
            "chunkSize": chunk_size,
            "chunkOverlap": chunk_overlap,
        }
        return self._c.request("POST", "/api/knowledge-bases", json=payload)

    def delete(self, kb_id: int) -> Any:
        return self._c.request("DELETE", f"/api/knowledge-bases/{kb_id}")

    def add_text(self, kb_id: int, title: str, content: str, source_type: str = "TEXT") -> Any:
        payload = {"title": title, "content": content, "sourceType": source_type}
        return self._c.request(
            "POST", f"/api/knowledge-bases/{kb_id}/documents/text", json=payload
        )

    def index(self, kb_id: int, document_id: int) -> Any:
        return self._c.request(
            "POST", f"/api/knowledge-bases/{kb_id}/documents/{document_id}/index"
        )

    def search(self, kb_id: int, query: str, top_k: int = 3) -> Any:
        payload = {"query": query, "topK": top_k}
        return self._c.request("POST", f"/api/knowledge-bases/{kb_id}/search", json=payload)
