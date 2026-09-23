"""Контракт каталога и неизменяемый CSV-адаптер."""
import os
from typing import Protocol
from app.domain.models import Contractor
from app.repositories.catalog import load_catalog


class Catalog(Protocol):
    backend: str

    def load(self) -> tuple[Contractor, ...]: ...


class CsvCatalog:
    backend = 'csv'

    def __init__(self, path):
        self._profiles = load_catalog(path)

    def load(self):
        return self._profiles


def configured_catalog(path):
    mode = os.getenv('CATALOG_BACKEND', 'csv').strip().lower()
    if mode == 'csv':
        return CsvCatalog(path)
    if mode == 'postgres':
        from app.repositories.postgres import PostgresCatalog
        url = os.getenv('DATABASE_URL', '')
        if not url:
            raise ValueError('Для PostgreSQL требуется DATABASE_URL')
        repository = PostgresCatalog(url)
        repository.initialize(path)
        return repository
    raise ValueError('CATALOG_BACKEND должен быть csv или postgres')
