"""Нормализация и проверка значений предметной области."""
import math
import re
from datetime import date as Date
from typing import Any

def normalized(value: str) -> str:
    """Сравнение без учёта регистра и лишних пробелов, без нечёткого поиска."""
    return " ".join(value.split()).casefold()


def split_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|") if part.strip())


def contains(values: tuple[str, ...], value: str) -> bool:
    return normalized(value) in {normalized(item) for item in values}


def number(value: Any, field: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: требуется число") from exc
    if isinstance(value, bool) or not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f"{field}: требуется конечное {'положительное' if positive else 'неотрицательное'} число")
    return result


def iso_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Дата должна иметь формат YYYY-MM-DD")
    return Date.fromisoformat(value).isoformat()


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


