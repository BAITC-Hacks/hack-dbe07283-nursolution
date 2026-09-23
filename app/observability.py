"""Потокобезопасные агрегаты процесса, без запросов пользователя и секретов."""
from collections import Counter
from threading import Lock
from time import monotonic


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._started = monotonic()
        self._counters = Counter()
        self._timings = {}

    def increment(self, name):
        with self._lock:
            self._counters[name] += 1

    def observe(self, name, seconds):
        with self._lock:
            value = self._timings.setdefault(name, dict(count=0, total_seconds=0.0, max_seconds=0.0))
            value['count'] += 1
            value['total_seconds'] += seconds
            value['max_seconds'] = max(value['max_seconds'], seconds)

    def snapshot(self):
        with self._lock:
            return dict(uptime_seconds=round(monotonic() - self._started, 3),
                        counters=dict(self._counters), durations={
                            key: {**value, 'mean_seconds': value['total_seconds'] / value['count']}
                            for key, value in self._timings.items()})
