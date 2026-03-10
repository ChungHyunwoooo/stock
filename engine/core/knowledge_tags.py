from .store import KnowledgeEntry, KnowledgeStore


class TagManager:
    def __init__(self, store: KnowledgeStore):
        self.store = store

    def get_all_tags(self) -> list[str]:
        """Return sorted unique tags across all entries."""
        tags: set[str] = set()
        for entry in self.store.scan():
            tags.update(entry.tags)
        return sorted(tags)

    def get_categories(self) -> list[str]:
        """Return categories (top-level directories under base_dir)."""
        categories: set[str] = set()
        for entry in self.store.scan():
            if entry.category:
                categories.add(entry.category)
        return sorted(categories)

    def get_entries_by_tag(self, tag: str) -> list[KnowledgeEntry]:
        return [e for e in self.store.scan() if tag in e.tags]

    def get_tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.store.scan():
            for tag in entry.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts
