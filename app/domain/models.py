"""Неизменяемые модели каталога."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Contractor:
    id: str
    anon_name: str
    categories: tuple[str, ...]
    city: str
    price_from_kzt: int
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: tuple[str, ...]
    description: str


