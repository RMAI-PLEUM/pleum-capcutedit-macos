"""Fresh CapCut-compatible UUID generation with collision tracking."""

from __future__ import annotations

import uuid


class CapCutIdFactory:
    def __init__(self, forbidden: set[str] | None = None) -> None:
        self.forbidden = set(forbidden or ())
        self.generated: set[str] = set()

    def new(self) -> str:
        while True:
            value = str(uuid.uuid4()).upper()
            if value not in self.forbidden and value not in self.generated:
                self.generated.add(value)
                return value
