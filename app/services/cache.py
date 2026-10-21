import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.utils.logging import log_event


class SummaryCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, summary: str) -> None: ...


@dataclass(frozen=True)
class _Entry:
    summary: str
    expires_at: float


class MemorySummaryCache:
    """Thread-safe process-local LRU/TTL cache; reads do not extend expiry."""

    def __init__(
        self,
        max_entries: int = 128,
        ttl_seconds: float = 300,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock if clock is not None else time.monotonic
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        # No await or I/O inside critical sections; also safe across caller threads.
        self._lock = threading.Lock()

    async def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= self._clock():
                del self._entries[key]
            else:
                self._entries.move_to_end(key)
                return entry.summary
        log_event("cache_lookup", "cache", cache_status="expired")
        return None

    async def set(self, key: str, summary: str) -> None:
        with self._lock:
            now = self._clock()
            expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
            for expired_key in expired:
                del self._entries[expired_key]
            self._entries[key] = _Entry(summary, now + self._ttl_seconds)
            self._entries.move_to_end(key)
            if len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
