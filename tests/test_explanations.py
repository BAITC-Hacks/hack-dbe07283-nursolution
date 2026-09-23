"""Дедлайн, кеш и конкуренция проверяются без сети и без настоящего API-ключа."""
import asyncio
from dataclasses import replace
import json
from threading import Event
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import Settings
from app.domain.models import Contractor
from app.services.cache import ExplanationCache
from app.services.explanations import ExplanationService
from app.services.matcher import EventMatcher


QUERY = dict(city="Алматы", date="2026-09-26", event_type="корпоратив",
             category="Ведущий", budget=1000000, language=None, duration=None)
PROFILE = Contractor("A", "Имя", ("Ведущий",), "Алматы", 500000, ("корпоратив",),
                     ("русский",), 6, (), "Проводит деловые конференции на 3000 человек.")


def valid_response(**kwargs):
    profiles = json.loads(kwargs["messages"][-1]["content"])["profiles"]
    items = [{"id": p["id"], "evidence_quote": p["evidence_options"][0] if p["evidence_options"] else None}
             for p in profiles]
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
        content=json.dumps({"explanations": items})))])


class CacheTests(unittest.TestCase):
    def test_ttl_expires_without_refresh_on_read(self):
        now = [10.0]
        cache = ExplanationCache(2, 5, clock=lambda: now[0])
        cache.put("key", {"quote": "fact"})
        now[0] = 14
        self.assertIsNotNone(cache.get("key"))
        now[0] = 15
        self.assertIsNone(cache.get("key"))

    def test_lru_evicts_and_returns_independent_values(self):
        cache = ExplanationCache(2, 60)
        cache.put("a", {"value": []})
        cache.put("b", {})
        result = cache.get("a")
        result["value"].append("modified")
        cache.put("c", {})
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), {"value": []})

    def test_zero_capacity_or_ttl_disables_storage(self):
        for size, ttl in ((0, 60), (2, 0)):
            cache = ExplanationCache(size, ttl)
            cache.put("a", {"data": 1})
            self.assertIsNone(cache.get("a"))


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.chat.completions.create.side_effect = valid_response
        self.service = ExplanationService(client=self.client, settings=Settings(request_timeout=0.1))
        self.addCleanup(self.service.close)

    def explain(self, selected=None, request=None):
        return self.service.explain(selected or [PROFILE], request or QUERY, monotonic() + 0.5)

    def test_repeat_uses_cache_without_calling_api(self):
        first, warning = self.explain()
        self.assertIsNone(warning)
        first["A"]["explanation"] = "modified by caller"
        second, warning = self.explain()
        self.assertNotEqual(second["A"]["explanation"], "modified by caller")
        self.assertIsNone(warning)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)

    def test_profile_request_and_prompt_changes_invalidate_cache(self):
        self.explain()
        changed = replace(PROFILE, description="Ведёт камерные деловые встречи на 20 человек.")
        result, _ = self.explain(selected=[changed])
        self.assertIn("20 человек", result["A"]["explanation"])
        self.explain(request={**QUERY, "budget": 800000})
        with patch("app.services.explanations.PROMPT_VERSION", "new-version"):
            self.explain()
        self.assertEqual(self.client.chat.completions.create.call_count, 4)

    def test_expired_cache_requeries_provider(self):
        now = [1.0]
        self.service.cache = ExplanationCache(2, 10, clock=lambda: now[0])
        self.explain()
        now[0] += 11
        self.explain()
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_errors_and_partial_answers_are_not_cached(self):
        for side_effect in (TimeoutError("private"), lambda **kwargs: SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"explanations": []}'))])):
            self.client.chat.completions.create.side_effect = side_effect
            _, warning = self.explain()
            self.assertTrue(warning)
        self.client.chat.completions.create.side_effect = valid_response
        result, warning = self.explain()
        self.assertIsNone(warning)
        self.assertEqual(result["A"]["explanation_source"], "openai")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)

    def test_expired_deadline_skips_api(self):
        result, warning = self.service.explain([PROFILE], QUERY, monotonic() - 1)
        self.assertEqual(result["A"]["explanation_source"], "python")
        self.assertIn("Время", warning)
        self.client.chat.completions.create.assert_not_called()

    def test_sync_timeout_and_late_response_are_not_cached(self):
        release = Event()
        self.addCleanup(release.set)
        def blocked(**kwargs):
            release.wait(2)
            return valid_response(**kwargs)
        self.client.chat.completions.create.side_effect = blocked
        started = monotonic()
        result, warning = self.service.explain([PROFILE], QUERY, started + 0.08)
        elapsed = monotonic() - started
        self.assertLess(elapsed, 0.7)
        self.assertEqual(result["A"]["explanation_source"], "python")
        self.assertIn("Время", warning)
        pending = next(iter(self.service._inflight.values()))
        release.set()
        pending.result(timeout=2)
        self.client.chat.completions.create.side_effect = valid_response
        self.explain()
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_http_deadline_returns_real_cards(self):
        release = Event()
        self.addCleanup(release.set)
        def blocked(**kwargs):
            release.wait(2)
            return valid_response(**kwargs)
        self.client.chat.completions.create.side_effect = blocked
        matcher = EventMatcher(client=self.client, settings=Settings(request_timeout=0.08))
        self.addCleanup(matcher.close)
        with TestClient(create_app(matcher=matcher)) as client:
            started = monotonic()
            response = client.post("/match", json=QUERY)
            elapsed = monotonic() - started
            self.assertLess(elapsed, 0.8)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(len(result["cards"]), 3)
            self.assertTrue(all(c["explanation_source"] == "python" for c in result["cards"]))
            self.assertIn("Время", result["warning"])
            self.assertEqual(client.get("/health").status_code, 200)
        release.set()

    def test_closed_service_does_not_start_work(self):
        self.service.close()
        _, warning = self.explain()
        self.assertTrue(warning)
        self.client.chat.completions.create.assert_not_called()


class AsyncExplanationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.release = Event()
        self.started = Event()
        self.client = Mock()
        def blocked(**kwargs):
            self.started.set()
            self.release.wait(3)
            return valid_response(**kwargs)
        self.client.chat.completions.create.side_effect = blocked
        self.service = ExplanationService(client=self.client, settings=Settings(llm_concurrency=1))

    async def asyncTearDown(self):
        self.release.set()
        self.service.close()

    async def begin(self):
        task = asyncio.create_task(self.service.aexplain([PROFILE], QUERY, monotonic() + 2))
        self.assertTrue(await asyncio.to_thread(self.started.wait, 1))
        return task

    async def test_parallel_identical_queries_share_one_call(self):
        first = await self.begin()
        second = asyncio.create_task(self.service.aexplain([PROFILE], QUERY, monotonic() + 2))
        # Даём второму запросу присоединиться к незавершённому первому.
        await asyncio.sleep(0)
        self.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(a, b)
        self.assertIsNone(a[1])
        self.assertEqual(self.client.chat.completions.create.call_count, 1)

    async def test_saturation_falls_back_without_queue(self):
        first = await self.begin()
        start = monotonic()
        result, warning = await self.service.aexplain([PROFILE], {**QUERY, "budget": 900000}, start + 2)
        self.assertLess(monotonic() - start, 0.5)
        self.assertIn("занят", warning)
        self.assertEqual(result["A"]["explanation_source"], "python")
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.release.set()
        await first

    async def test_cancelled_waiter_does_not_cancel_shared_work(self):
        first = await self.begin()
        second = asyncio.create_task(self.service.aexplain([PROFILE], QUERY, monotonic() + 2))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.release.set()
        _, warning = await second
        self.assertIsNone(warning)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)

    async def test_each_waiter_has_its_own_deadline(self):
        first = await self.begin()
        _, warning = await self.service.aexplain([PROFILE], QUERY, monotonic() + 0.03)
        self.assertIn("Время", warning)
        self.release.set()
        _, first_warning = await first
        self.assertIsNone(first_warning)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
