"""Реальный PostgreSQL, отдельная временная схема для каждого теста."""
import os
from dataclasses import asdict, replace
from uuid import uuid4
from unittest import TestCase, skipUnless
from unittest.mock import patch
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from app.config import DEFAULT_CSV
from app.repositories.catalog import load_catalog
from app.repositories.postgres import PostgresCatalog, CatalogConflict
from app.services.matcher import EventMatcher


@skipUnless(os.getenv('POSTGRES_TEST_URL'), 'Set POSTGRES_TEST_URL to run database integration tests')
class PostgresTests(TestCase):
    def setUp(self):
        self.url=os.environ['POSTGRES_TEST_URL']
        self.schema='nur_test_'+uuid4().hex
        with psycopg.connect(self.url) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        schema=self.schema
        class IsolatedCatalog(PostgresCatalog):
            def _connect(inner):
                conn=super()._connect()
                conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                return conn
        self.repository=IsolatedCatalog(self.url)
        self.repository.initialize(DEFAULT_CSV)

    def cleanup_schema(self):
        with psycopg.connect(self.url) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_seed_is_idempotent_and_matches_csv(self):
        self.repository.initialize(DEFAULT_CSV)
        self.assertEqual(sorted(self.repository.load(),key=lambda p:p.id),sorted(load_catalog(DEFAULT_CSV),key=lambda p:p.id))
        csv=EventMatcher(use_llm=False)
        db=EventMatcher(use_llm=False,repository=self.repository)
        self.addCleanup(csv.close);self.addCleanup(db.close)
        query=dict(city='Алматы',date='2026-09-26',event_type='корпоратив',category='Ведущий',budget=1000000)
        self.assertEqual(csv.match(**query),db.match(**query))

    def test_edit_is_visible_to_existing_matcher_and_stale_edit_conflicts(self):
        matcher=EventMatcher(use_llm=False,repository=self.repository)
        self.addCleanup(matcher.close)
        profile=next(p for p in self.repository.load() if p.id=='HK-44733')
        query=dict(city='Алматы',date='2026-09-26',event_type='корпоратив',category='Ведущий',budget=1000000)
        self.assertIn(profile.id,[c['id'] for c in matcher.match(**query)['cards']])
        updated=replace(profile,busy_dates=(*profile.busy_dates,'2026-09-26'))
        record=self.repository.save(updated,1)
        self.assertEqual(record['revision'],2)
        self.assertNotIn(profile.id,[c['id'] for c in matcher.match(**query)['cards']])
        with self.assertRaises(CatalogConflict): self.repository.save(profile,1)

    def test_editor_create_update_and_validation(self):
        from app.api.application import create_app
        matcher=EventMatcher(use_llm=False,repository=self.repository)
        self.addCleanup(matcher.close)
        with patch.dict(os.environ,{'ADMIN_TOKEN':'integration-token'}), TestClient(create_app(matcher=matcher)) as client:
            headers={'Authorization':'Bearer integration-token'}
            profile=asdict(replace(self.repository.load()[0],id='TEST-NEW'))
            response=client.post('/admin/api/contractors',json=profile,headers=headers)
            self.assertEqual(response.status_code,201)
            profile['anon_name']='Новое имя'
            update={'profile':profile,'revision':1}
            self.assertEqual(client.put('/admin/api/contractors/TEST-NEW',json=update,headers=headers).status_code,200)
            self.assertEqual(client.put('/admin/api/contractors/TEST-NEW',json=update,headers=headers).status_code,409)
            self.assertEqual(client.post('/admin/api/contractors',json=profile,headers=headers).status_code,409)
            self.assertEqual(next(p for p in self.repository.load() if p.id=='TEST-NEW').anon_name,'Новое имя')
