"""Tiny in-memory sliding-window limiter for expensive endpoints (single process).

Thread-safe (FastAPI runs sync endpoints in a thread pool) and bounded: keys whose window has
passed are forgotten, so a stream of new keys cannot grow memory without limit.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict


class RateLimiter:
    def __init__(self, max_calls: int, per_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_calls, self.per, self.clock = max_calls, per_seconds, clock
        self.hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def _sweep(self, now: float) -> None:
        for key in [k for k, q in self.hits.items() if not q or now - q[-1] > self.per]:
            del self.hits[key]
        self._last_sweep = now

    def _window(self, key: str, now: float) -> Deque[float]:
        if now - self._last_sweep > self.per:
            self._sweep(now)
        q = self.hits.setdefault(key, deque())
        while q and now - q[0] > self.per:
            q.popleft()
        return q

    def allow(self, key: str) -> bool:
        """Count this call and say whether it is within the limit."""
        with self._lock:
            now = self.clock()
            q = self._window(key, now)
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            return True

    def blocked(self, key: str) -> bool:
        """Whether `key` is over the limit, without counting a call (for counting failures only)."""
        with self._lock:
            return len(self._window(key, self.clock())) >= self.max_calls

    def record(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            self._window(key, now).append(now)
