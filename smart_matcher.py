"""Совместимый импорт EventMatcher и прежняя команда запуска демо."""
from app.config import DEFAULT_CSV
from app.domain.models import Contractor
from app.services.matcher import EventMatcher

__all__ = ["EventMatcher", "Contractor", "DEFAULT_CSV"]

if __name__ == "__main__":
    from app.cli import main
    main()
