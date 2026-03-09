from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import frontmatter


@dataclass
class KnowledgeEntry:
    title: str
    path: str
    tags: list[str] = field(default_factory=list)
    category: str = ""
    source: str = ""
    summary: str = ""
    created_at: date | None = None


class KnowledgeStore:
    def __init__(self, base_dir: str | Path = "strategies/knowledge"):
        self.base_dir = Path(base_dir)
        self._entries: list[KnowledgeEntry] | None = None

    def scan(self) -> list[KnowledgeEntry]:
        """Scan all .md files, parse frontmatter, return entries."""
        entries = []
        for md_file in sorted(self.base_dir.rglob("*.md")):
            try:
                post = frontmatter.load(str(md_file))
            except Exception:
                continue

            meta = post.metadata
            raw_tags = meta.get("tags", [])
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

            raw_date = meta.get("date") or meta.get("created_at")
            created_at: date | None = None
            if isinstance(raw_date, date):
                created_at = raw_date
            elif isinstance(raw_date, str):
                try:
                    created_at = date.fromisoformat(raw_date)
                except ValueError:
                    pass

            # category: top-level directory under base_dir
            try:
                rel = md_file.relative_to(self.base_dir)
                category = meta.get("category") or (rel.parts[0] if len(rel.parts) > 1 else "")
            except ValueError:
                category = meta.get("category", "")

            entries.append(
                KnowledgeEntry(
                    title=meta.get("title", md_file.stem),
                    path=str(md_file),
                    tags=list(raw_tags),
                    category=category,
                    source=meta.get("source", ""),
                    summary=meta.get("summary", ""),
                    created_at=created_at,
                )
            )

        self._entries = entries
        return entries

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
    ) -> list[KnowledgeEntry]:
        """Filter entries by query (title substring), tags, category."""
        entries = self._entries if self._entries is not None else self.scan()

        result = entries
        if query:
            q = query.lower()
            result = [e for e in result if q in e.title.lower()]
        if tags:
            tag_set = set(tags)
            result = [e for e in result if tag_set.intersection(e.tags)]
        if category:
            result = [e for e in result if e.category == category]

        return result

    def get_entry(self, path: str) -> KnowledgeEntry | None:
        entries = self._entries if self._entries is not None else self.scan()
        for entry in entries:
            if entry.path == path:
                return entry
        return None
