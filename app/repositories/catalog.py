"""Чтение и валидация CSV без сетевых зависимостей."""
import csv
from pathlib import Path
from app.domain.models import Contractor
from app.domain.validation import number, split_values, iso_date

def load_catalog(path: str | Path) -> tuple[Contractor, ...]:
    required = set(Contractor.__dataclass_fields__)
    profiles = []
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"В CSV отсутствуют поля: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("неверное число столбцов")
                fields = {key: row[key].strip() for key in required}
                for key in ("id", "anon_name", "city", "categories", "event_formats", "languages"):
                    if not fields[key]:
                        raise ValueError(f"пустое поле {key}")
                if fields["id"] in seen:
                    raise ValueError(f"повторяющийся id {fields['id']}")
                price = number(fields["price_from_kzt"], "price_from_kzt")
                if not price.is_integer():
                    raise ValueError("price_from_kzt должен быть целым числом тенге")
                for key in ("categories", "event_formats", "languages", "busy_dates"):
                    fields[key] = split_values(fields[key])
                for key in ("categories", "event_formats", "languages"):
                    if not fields[key]:
                        raise ValueError(f"пустой список {key}")
                fields["busy_dates"] = tuple(iso_date(day) for day in fields["busy_dates"])
                fields["price_from_kzt"] = int(price)
                fields["max_hours"] = (number(fields["max_hours"], "max_hours", positive=True)
                                       if fields["max_hours"] else None)
                profiles.append(Contractor(**fields))
                seen.add(fields["id"])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"CSV, строка {line}: {exc}") from exc
    return tuple(profiles)

