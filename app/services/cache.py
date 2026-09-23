"""Ограниченный TTL/LRU-кеш: только проверенные объяснения, без внешнего Redis."""
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic


class ExplanationCache:
    def __init__(self, max_entries=256, ttl=600.0, *, clock=monotonic):
        self.max_entries = max_entries
        self.ttl = ttl
        self.clock = clock
        self._entries = OrderedDict()
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires, value = item
            if expires <= self.clock():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return deepcopy(value)

    def put(self, key, value):
        if self.max_entries == 0 or self.ttl == 0:
            return
        with self._lock:
            now = self.clock()
            for expired in [k for k, (expires, _) in self._entries.items() if expires <= now]:
                del self._entries[expired]
            self._entries[key] = (now + self.ttl, deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
