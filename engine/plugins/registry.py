from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PluginSpec(Generic[T]):
    name: str
    factory: Callable[..., T]
    description: str = ""


class PluginRegistry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._plugins: dict[str, PluginSpec[T]] = {}

    def register(self, name: str, factory: Callable[..., T], description: str = "") -> None:
        self._plugins[name] = PluginSpec(name=name, factory=factory, description=description)

    def create(self, name: str, **kwargs) -> T:
        try:
            plugin = self._plugins[name]
        except KeyError as exc:
            raise KeyError(f"Unknown {self.kind} plugin: {name}") from exc
        return plugin.factory(**kwargs)

    def names(self) -> list[str]:
        return sorted(self._plugins)

    def specs(self) -> list[PluginSpec[T]]:
        return [self._plugins[name] for name in self.names()]
