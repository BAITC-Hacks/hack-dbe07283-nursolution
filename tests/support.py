"""API-тесты используют CSV и заглушки независимо от пользовательского .env."""
from unittest import TestCase
from unittest.mock import patch


class IsolatedAPITestCase(TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.dict('os.environ', {
            'CATALOG_BACKEND': 'csv',
            'DATABASE_URL': '',
            'MATCHER_CSV_PATH': '',
            'MATCHER_USE_LLM': 'false',
            'OPENAI_API_KEY': '',
            'ADMIN_TOKEN': '',
            'MATCHER_TIMEOUT_SECONDS': '8',
            'EXPLANATION_CACHE_TTL_SECONDS': '600',
            'EXPLANATION_CACHE_MAX_ENTRIES': '256',
            'LLM_MAX_CONCURRENCY': '4',
            'CORS_ORIGINS': 'http://localhost:5173',
        })
        self.addCleanup(patcher.stop)
        patcher.start()
