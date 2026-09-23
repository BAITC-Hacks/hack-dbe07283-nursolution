"""HTTP-контракт API: реальные matcher/CSV, без сети и расходов OpenAI."""
import asyncio
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import main
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api import create_app
from smart_matcher import DEFAULT_CSV, EventMatcher
from tests.support import IsolatedAPITestCase


class APITests(IsolatedAPITestCase):
    def setUp(self):
        super().setUp()
        self.matcher = EventMatcher(use_llm=False)
        self.addCleanup(self.matcher.close)
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.client = stack.enter_context(TestClient(create_app(matcher=self.matcher)))
        self.query = dict(city="Алматы", date="2026-09-26", event_type="корпоратив",
                          category="Ведущий", budget=2000000)

    def test_success_and_stable_order(self):
        first = self.client.post("/match", json=self.query)
        second = self.client.post("/match", json=self.query)
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(body, second.json())
        self.assertEqual(body["status"], "matched")
        self.assertEqual(len(body["cards"]), 3)
        for card in body["cards"]:
            self.assertTrue(card["explanation"])
            self.assertIn("evidence", card)
            self.assertLessEqual(card["price_from_kzt"], self.query["budget"])

    def test_three_outcomes_are_http_success(self):
        cases = [(self.query, "matched"), ({**self.query, "category": "Несуществующая"}, "no_category_in_city"),
                 ({**self.query, "budget": 1}, "no_matches")]
        for query, expected in cases:
            with self.subTest(expected=expected):
                response = self.client.post("/match", json=query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], expected)
                self.assertTrue(response.json()["message"])

    def test_suggestion_can_be_resubmitted(self):
        query = {**self.query, "budget": 1}
        result = self.client.post("/match", json=query).json()
        self.assertTrue(result["suggestions"])
        for suggestion in result["suggestions"]:
            response = self.client.post("/match", json={**query, suggestion["field"]: suggestion["value"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["eligible_count"], suggestion["candidate_count"])

    def test_invalid_fields(self):
        cases = [("city", " "), ("city", 123), ("date", "2026-02-30"), ("date", "20260926"),
                 ("date", 12345), ("budget", -1), ("budget", "2000000"), ("budget", True),
                 ("duration", 0), ("duration", False), ("language", ""), ("category", "x" * 201),
                 ("api_key", "must-not-be-echoed")]
        with patch.object(self.matcher, "amatch", wraps=self.matcher.amatch) as match:
            for field, value in cases:
                with self.subTest(field=field, value=value):
                    response = self.client.post("/match", json={**self.query, field: value})
                    self.assertEqual(response.status_code, 422)
                    error = response.json()["error"]
                    self.assertEqual(error["code"], "validation_error")
                    self.assertIn(field, [item["field"] for item in error["fields"]])
                    self.assertNotIn("must-not-be-echoed", response.text)
            match.assert_not_called()

    def test_malformed_and_missing_body(self):
        for content in ('{"city":', '{}', 'null', '[]', '{"budget": NaN}'):
            response = self.client.post("/match", content=content, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_optional_fields_and_whitespace(self):
        response = self.client.post("/match", json={**self.query, "city": " Алматы ",
                                                    "language": None, "duration": None})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "matched")
        with patch.object(self.matcher, "amatch", wraps=self.matcher.amatch) as match:
            self.client.post("/match", json={**self.query, "duration": 4, "language": "русский"})
            self.assertEqual(match.call_args.kwargs["duration"], 4)
            self.assertEqual(match.call_args.kwargs["language"], "русский")

    def test_empty_result_does_not_call_llm(self):
        self.matcher.use_llm = True
        self.matcher.explanations.client = Mock()
        response = self.client.post("/match", json={**self.query, "budget": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.matcher.explanations.client.mock_calls, [])

    def test_api_failure_still_returns_cards(self):
        self.matcher.use_llm = True
        self.matcher.explanations.client = Mock()
        self.matcher.explanations.client.chat.completions.create.side_effect = TimeoutError("private")
        response = self.client.post("/match", json=self.query)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cards"])
        self.assertTrue(response.json()["warning"])
        self.assertNotIn("private", response.text)

    def test_health_and_openapi(self):
        response = self.client.get("/health")
        self.assertEqual(response.json(), {"status": "ok", "total_profiles": 66, "catalog_backend": "csv", "llm_enabled": False})
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("MatchRequest", schema["components"]["schemas"])
        self.assertIn("MatchResponse", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])
        self.assertEqual(schema["paths"]["/match"]["post"]["responses"]["422"]["content"]["application/json"]["schema"],
                         {"$ref": "#/components/schemas/ErrorResponse"})

    def test_frontend_and_assets_are_served(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('id="order-form"', page.text)
        self.assertIn('href="/selection"', page.text)
        selection = self.client.get("/selection")
        self.assertEqual(selection.status_code, 200)
        self.assertIn('id="order-form"', selection.text)
        for asset in ("styles.css", "app.js", "home.js", "about.js", "cards.js", "ui.js", "favicon.svg"):
            response = self.client.get(f"/assets/{asset}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content)
        self.assertEqual(self.client.get("/assets/.env").status_code, 404)

    def test_catalog_options_come_from_loaded_profiles(self):
        response = self.client.get("/catalog")
        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual(catalog["total_profiles"], 66)
        self.assertEqual(catalog["cities"], sorted({p.city for p in self.matcher.contractors}))
        self.assertEqual(catalog["categories"], sorted({c for p in self.matcher.contractors for c in p.categories}))
        self.assertIn("корпоратив", catalog["event_types"])
        self.assertIn("русский", catalog["languages"])

    def test_cors_preflight(self):
        for origin, expected in (("http://localhost:5173", 200), ("https://unlisted.example", 400)):
            response = self.client.options("/match", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
            else:
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_not_found_and_method_errors(self):
        for path, code in (("/missing", 404), ("/match", 405)):
            response = self.client.get(path)
            self.assertEqual(response.status_code, code)
            self.assertEqual(response.json()["error"]["code"], "http_error")

    def test_unexpected_error_is_not_exposed(self):
        with TestClient(create_app(matcher=self.matcher), raise_server_exceptions=False) as client:
            with patch.object(self.matcher, "amatch", side_effect=RuntimeError("secret-key-private-path")):
                response = client.post("/match", json=self.query)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-key-private-path", response.text)
        self.assertEqual(response.json()["error"]["code"], "internal_error")

    def test_slow_match_does_not_block_health(self):
        started, release = Event(), Event()
        result = self.matcher.match(**self.query)
        async def slow_match(**kwargs):
            started.set()
            if not await asyncio.to_thread(release.wait, 5):
                raise TimeoutError("Test did not release matcher")
            return result
        with patch.object(self.matcher, "amatch", side_effect=slow_match):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.client.post, "/match", json=self.query)
                try:
                    self.assertTrue(started.wait(timeout=2))
                    self.assertEqual(self.client.get("/health").status_code, 200)
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=2).status_code, 200)


class LifecycleTests(IsolatedAPITestCase):
    def test_load_once_and_close_on_shutdown(self):
        with patch("app.api.application.EventMatcher", wraps=EventMatcher) as factory:
            application = create_app(csv_path=DEFAULT_CSV, use_llm=False)
            factory.assert_not_called()
            with TestClient(application) as client:
                instance = application.state.matcher
                instance.close = Mock(wraps=instance.close)
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/health").status_code, 200)
                factory.assert_called_once()
            instance.close.assert_called_once()
            self.assertFalse(hasattr(application.state, "matcher"))

    def test_bad_csv_fails_startup(self):
        with self.assertRaises(FileNotFoundError):
            with TestClient(create_app(csv_path="missing-test-dataset.csv", use_llm=False)):
                self.fail("Не должен запускаться с отсутствующим CSV")

    def test_environment_offline_mode(self):
        with patch.dict("os.environ", {"MATCHER_USE_LLM": "false"}):
            application = create_app(csv_path=DEFAULT_CSV)
            with TestClient(application):
                self.assertFalse(application.state.matcher.use_llm)


if __name__ == "__main__":
    main()
