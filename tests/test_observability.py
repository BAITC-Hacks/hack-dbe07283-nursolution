"""Проверка метрик и границ доступа редактора без внешних сервисов."""
import json
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.services.matcher import EventMatcher
from tests.test_explanations import valid_response
from tests.support import IsolatedAPITestCase


class ObservabilityTests(IsolatedAPITestCase):
    def test_provider_cache_and_http_are_counted_without_query_values(self):
        provider=Mock()
        provider.chat.completions.create.side_effect=valid_response
        matcher=EventMatcher(client=provider)
        self.addCleanup(matcher.close)
        with TestClient(create_app(matcher=matcher)) as client:
            query=dict(city='Алматы',date='2026-09-26',event_type='корпоратив',category='Ведущий',budget=1000000)
            first=client.post('/match',json=query)
            second=client.post('/match',json=query)
            self.assertEqual(first.status_code,200)
            self.assertNotEqual(first.headers['x-request-id'],second.headers['x-request-id'])
            metrics=client.get('/metrics').json()
            self.assertEqual(metrics['counters']['provider_calls'],1)
            self.assertEqual(metrics['counters']['cache_hit'],1)
            self.assertEqual(metrics['counters']['http_match_2xx'],2)
            self.assertEqual(metrics['durations']['http_match']['count'],2)
            self.assertNotIn('Алматы',json.dumps(metrics,ensure_ascii=False))
            self.assertNotIn('HK-',json.dumps(metrics))

    def test_validation_and_provider_errors_are_counted(self):
        provider=Mock();provider.chat.completions.create.side_effect=RuntimeError('SECRET')
        matcher=EventMatcher(client=provider)
        self.addCleanup(matcher.close)
        with TestClient(create_app(matcher=matcher)) as client:
            client.post('/match',json={})
            client.post('/match',json=dict(city='Алматы',date='2026-09-26',event_type='корпоратив',category='Ведущий',budget=1000000))
            metrics=client.get('/metrics').json()
            self.assertEqual(metrics['counters']['http_match_4xx'],1)
            self.assertEqual(metrics['counters']['provider_errors'],1)
            self.assertNotIn('SECRET',json.dumps(metrics))


class AdminTests(IsolatedAPITestCase):
    def test_editor_validation_messages_describe_the_rejected_field(self):
        with patch.dict('os.environ', {'ADMIN_TOKEN': 'test-editor-token'}), TestClient(create_app(use_llm=False)) as client:
            headers = {'Authorization': 'Bearer test-editor-token'}
            profile = client.get('/admin/api/contractors', headers=headers).json()['records'][0]['profile']
            profile['id'] = 'invalid id'
            response = client.post('/admin/api/contractors', json=profile, headers=headers)
            self.assertEqual(response.status_code, 422)
            error = response.json()['error']['fields'][0]
            self.assertEqual(error['field'], 'id')
            self.assertIn('ID', error['message'])
            self.assertNotIn('Дата', error['message'])

            profile['id'] = 'TEST-VALID-ID'
            profile['description'] = 'x' * 10001
            response = client.put('/admin/api/contractors/TEST-VALID-ID',
                                  json={'profile': profile, 'revision': 1}, headers=headers)
            self.assertEqual(response.status_code, 422)
            error = response.json()['error']['fields'][0]
            self.assertEqual(error['field'], 'profile.description')
            self.assertIn('10000', error['message'])

    def test_admin_disabled_without_key(self):
        with patch.dict('os.environ',{'ADMIN_TOKEN':''}), TestClient(create_app(use_llm=False)) as client:
            self.assertEqual(client.get('/admin/api/contractors').status_code,503)

    def test_csv_is_readonly_and_auth_is_required(self):
        with patch.dict('os.environ',{'ADMIN_TOKEN':'test-editor-token'}), TestClient(create_app(use_llm=False)) as client:
            self.assertEqual(client.get('/admin/api/contractors').status_code,401)
            self.assertEqual(client.get('/admin/api/contractors',headers={'Authorization':'Bearer wrong'}).status_code,401)
            headers={'Authorization':'Bearer test-editor-token'}
            response=client.get('/admin/api/contractors',headers=headers).json()
            self.assertFalse(response['editable'])
            self.assertEqual(len(response['records']),66)
            profile=response['records'][0]['profile']
            self.assertEqual(client.post('/admin/api/contractors',json=profile,headers=headers).status_code,409)
            profile['busy_dates']=['2026-02-30']
            self.assertEqual(client.post('/admin/api/contractors',json=profile,headers=headers).status_code,422)
