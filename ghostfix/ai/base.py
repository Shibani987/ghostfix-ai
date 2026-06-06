from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str | None:
        """Send prompt, return raw text response."""
        ...
