
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from engine.core.knowledge_store import KnowledgeStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

class KnowledgeResponse(BaseModel):
    title: str
    path: str
    tags: list[str]
    category: str
    source: str
    summary: str
    created_at: str | None

def _entry_to_response(e) -> KnowledgeResponse:  # type: ignore[no-untyped-def]
    return KnowledgeResponse(
        title=e.title,
        path=e.path,
        tags=e.tags,
        category=e.category,
        source=e.source,
        summary=e.summary,
        created_at=str(e.created_at) if e.created_at else None,
    )

@router.get("", response_model=list[KnowledgeResponse])
def list_knowledge(
    query: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    base_dir: str = "strategies/knowledge",
) -> list[KnowledgeResponse]:
    store = KnowledgeStore(base_dir)
    tags = [tag] if tag else None
    entries = store.search(query=query, tags=tags, category=category)
    return [_entry_to_response(e) for e in entries]

@router.get("/search", response_model=list[KnowledgeResponse])
def search_knowledge(
    q: str,
    base_dir: str = "strategies/knowledge",
) -> list[KnowledgeResponse]:
    store = KnowledgeStore(base_dir)
    entries = store.search(query=q)
    return [_entry_to_response(e) for e in entries]
