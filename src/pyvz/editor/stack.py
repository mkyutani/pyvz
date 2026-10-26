"""The text stack: lines and blocks cut or stored, shared by all texts (VZ)."""

from __future__ import annotations

LIMIT = 1_000_000  # characters; VZ's was 64KB


class TextStack:
    def __init__(self, limit: int = LIMIT) -> None:
        self.limit = limit
        self.items: list[tuple[str, str]] = []  # (kind, text), the top last

    def __len__(self) -> int:
        return len(self.items)

    def push(self, kind: str, text: str) -> None:
        """Push text. When the stack is over its limit, the oldest go first (VZ)."""
        self.items.append((kind, text))
        total = sum(len(t) for _, t in self.items)
        while total > self.limit and len(self.items) > 1:
            total -= len(self.items.pop(0)[1])

    def pop(self) -> tuple[str, str] | None:
        return self.items.pop() if self.items else None

    def top(self) -> tuple[str, str] | None:
        return self.items[-1] if self.items else None

    def clear(self) -> None:
        self.items.clear()
