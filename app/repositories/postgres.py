"""PostgreSQL: транзакционные записи, версии и свежий снимок для каждого поиска."""
from dataclasses import asdict
import psycopg
from psycopg.types.json import Jsonb
from psycopg.conninfo import conninfo_to_dict
from app.domain.models import Contractor
from app.repositories.catalog import load_catalog


class CatalogConflict(Exception):
    pass


class PostgresCatalog:
    backend = 'postgres'

    def __init__(self, url):
        self._url = url

    def _connect(self):
        options = conninfo_to_dict(self._url).get('options', '')
        return psycopg.connect(self._url, connect_timeout=3,
                              options=options + ' -c statement_timeout=3000 -c lock_timeout=3000')

    def initialize(self, csv_path):
        # Один transactional bootstrap даже при одновременном старте workers.
        with self._connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(790079)')
            connection.execute('''CREATE TABLE IF NOT EXISTS catalog_meta (
                version integer PRIMARY KEY)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS contractors (
                id text PRIMARY KEY,
                profile jsonb NOT NULL,
                revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0))''')
            versions = connection.execute('SELECT version FROM catalog_meta').fetchall()
            if versions and versions != [(1,)]:
                raise RuntimeError('Неподдерживаемая версия схемы каталога')
            if not versions:
                for profile in load_catalog(csv_path):
                    connection.execute('INSERT INTO contractors (id, profile) VALUES (%s, %s)',
                                       (profile.id, Jsonb(asdict(profile))))
                connection.execute('INSERT INTO catalog_meta (version) VALUES (1)')

    @staticmethod
    def _profile(values):
        values = dict(values)
        for key in ('categories', 'event_formats', 'languages', 'busy_dates'):
            values[key] = tuple(values[key])
        return Contractor(**values)

    def load(self):
        with self._connect() as connection:
            rows = connection.execute('SELECT profile FROM contractors ORDER BY id').fetchall()
        return tuple(self._profile(row[0]) for row in rows)

    def records(self):
        with self._connect() as connection:
            rows = connection.execute('SELECT profile, revision FROM contractors ORDER BY id').fetchall()
        return [dict(profile=row[0], revision=row[1]) for row in rows]

    def save(self, profile, revision=None):
        try:
            with self._connect() as connection:
                if revision is None:
                    row = connection.execute('''INSERT INTO contractors (id, profile) VALUES (%s, %s)
                        RETURNING revision''', (profile.id, Jsonb(asdict(profile)))).fetchone()
                else:
                    row = connection.execute('''UPDATE contractors SET profile=%s, revision=revision+1
                        WHERE id=%s AND revision=%s RETURNING revision''',
                        (Jsonb(asdict(profile)), profile.id, revision)).fetchone()
                    if row is None:
                        raise CatalogConflict('Профиль изменён другим редактором. Обновите список.')
        except psycopg.errors.UniqueViolation:
            raise CatalogConflict('Этот id уже существует.') from None
        return dict(profile=asdict(profile), revision=row[0])
