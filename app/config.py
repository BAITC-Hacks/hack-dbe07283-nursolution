"""Пути и настройки процесса. Секреты не входят в модели HTTP-ответов."""
from dataclasses import dataclass
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "hackathon dataset anonymized .csv"

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    request_timeout: float = 8.0
    cache_ttl: float = 600.0
    cache_size: int = 256
    llm_concurrency: int = 4

    def __post_init__(self):
        if not math.isfinite(self.request_timeout) or not 0 < self.request_timeout <= 9:
            raise ValueError("MATCHER_TIMEOUT_SECONDS должен быть больше 0 и не больше 9")
        if not math.isfinite(self.cache_ttl) or self.cache_ttl < 0:
            raise ValueError("EXPLANATION_CACHE_TTL_SECONDS должен быть конечным и неотрицательным")
        if self.cache_size < 0 or self.llm_concurrency < 1:
            raise ValueError("Размер кеша должен быть >= 0, лимит параллельных LLM-вызовов >= 1")

    @classmethod
    def from_env(cls):
        return cls(
            request_timeout=float(os.getenv("MATCHER_TIMEOUT_SECONDS", "8")),
            cache_ttl=float(os.getenv("EXPLANATION_CACHE_TTL_SECONDS", "600")),
            cache_size=int(os.getenv("EXPLANATION_CACHE_MAX_ENTRIES", "256")),
            llm_concurrency=int(os.getenv("LLM_MAX_CONCURRENCY", "4")),
        )
