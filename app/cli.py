"""Три демонстрационных сценария подбора."""
import argparse
import json
import sys
from pathlib import Path
from app.config import DEFAULT_CSV
from app.services.matcher import EventMatcher

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--offline", action="store_true", help="Демо без запросов к OpenAI")
    args = parser.parse_args()
    matcher = EventMatcher(args.csv, use_llm=not args.offline)
    scenarios = [
        ("Плотная категория", dict(city="Алматы", date="2026-09-26", event_type="корпоратив",
                                   category="Ведущий", budget=2_000_000)),
        ("Редкая категория", dict(city="Алматы", date="2026-09-26", event_type="свадьба",
                                  category="Флорист", budget=2_000_000)),
        ("Пустая выдача с аналитикой", dict(city="Алматы", date="2026-09-26", event_type="корпоратив",
                                            category="Ведущий", budget=1)),
    ]
    try:
        for title, query in scenarios:
            print(f"\n{title}")
            print(json.dumps(matcher.match(**query), ensure_ascii=False, indent=2))
    finally:
        matcher.close()


if __name__ == "__main__":
    main()
