"""Поведенческие тесты без сети и API-ключа: python -m unittest -v."""
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json

from smart_matcher import Contractor, EventMatcher, DEFAULT_CSV


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profiles.csv"
        self.query = dict(city="Алматы", date="2026-09-26", event_type="свадьба",
                          category="Ведущий", budget=300000, language="русский")

    def row(self, identifier="A", **changes):
        row = dict(id=identifier, anon_name=f"Имя {identifier}", categories="Ведущий|Музыкант",
                   city="Алматы", price_from_kzt=200000, event_formats="свадьба|той",
                   languages="русский|казахский", max_hours=6, busy_dates="",
                   description=f"Проводит церемонии по сценарию {identifier}.")
        row.update(changes)
        return row

    def matcher(self, rows, **kwargs):
        with self.path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(Contractor.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(rows)
        return EventMatcher(self.path, **kwargs)

    def test_all_filters_and_exclusive_counters(self):
        rows = [self.row("city", city="Астана"), self.row("category", categories="Фотограф"),
                self.row("budget", price_from_kzt=400000, busy_dates=self.query["date"]),
                self.row("date", busy_dates=self.query["date"]),
                self.row("event_type", event_formats="корпоратив"),
                self.row("language", languages="английский"),
                self.row("duration", max_hours=2), self.row("duration_unknown", max_hours="")]
        client = Mock()
        result = self.matcher(rows, client=client).match(**self.query, duration=4)
        self.assertEqual(result["status"], "no_matches")
        self.assertEqual(result["scope_count"], 6)
        self.assertTrue(all(n == 1 for n in result["rejection_counts"].values()))
        self.assertIn("400 000", result["message"])
        self.assertEqual(client.mock_calls, [])

    def test_absent_category_never_calls_llm(self):
        client = Mock()
        result = self.matcher([self.row(city="Астана")], client=client).match(**self.query)
        self.assertEqual(result["status"], "no_category_in_city")
        self.assertTrue(result["message"])
        self.assertEqual(client.mock_calls, [])

    def test_ranking_independent_of_csv_order(self):
        rows = [self.row("Z", price_from_kzt=300000), self.row("B"), self.row("A"),
                self.row("D", price_from_kzt=100000)]
        for ordered in (rows, list(reversed(rows))):
            matcher = self.matcher(ordered, use_llm=False)
            for _ in range(2):
                result = matcher.match(**self.query)
                self.assertEqual([c["id"] for c in result["cards"]], ["Z", "A", "B"])
                self.assertEqual(result["eligible_count"], 4)

    def test_rare_category_and_normalization(self):
        result = self.matcher([self.row()], use_llm=False).match(
            **{**self.query, "city": " АЛМАТЫ ", "category": " музыкант ", "language": " РУССКИЙ "})
        self.assertEqual(len(result["cards"]), 1)
        self.assertIn("Меньше трёх", result["message"])

    def test_language_optional_and_duration_boundary(self):
        matcher = self.matcher([self.row(languages="казахский")], use_llm=False)
        self.assertEqual(matcher.match(**{**self.query, "language": None}, duration=6)["status"], "matched")
        self.assertEqual(matcher.match(**self.query)["status"], "no_matches")

    def test_card_facts_preserve_budget_and_requested_conditions(self):
        matcher = self.matcher([self.row()], use_llm=False)
        self.addCleanup(matcher.close)
        card = matcher.match(**{**self.query, "language": " русский "}, duration=4)["cards"][0]
        facts = card["match_facts"]
        self.assertEqual(facts["budget_difference"], 100000)
        self.assertEqual(facts["budget"], self.query["budget"])
        self.assertEqual(facts["date"], self.query["date"])
        self.assertEqual(facts["date_status"], "not_marked_busy")
        self.assertEqual(facts["language"], "русский")
        self.assertEqual((facts["duration"], facts["max_hours"]), (4, 6))
        self.assertIn(card["evidence"]["quote"].rstrip("."), card["explanation"])

    def test_card_facts_do_not_invent_optional_conditions(self):
        matcher = self.matcher([self.row(max_hours="", description="")], use_llm=False)
        self.addCleanup(matcher.close)
        card = matcher.match(**{**self.query, "language": None})["cards"][0]
        self.assertIsNone(card["match_facts"]["language"])
        self.assertIsNone(card["match_facts"]["duration"])
        self.assertIsNone(card["match_facts"]["max_hours"])
        self.assertIsNone(card["evidence"])
        self.assertIn("свадьба", card["explanation"])

    def test_card_facts_allow_zero_budget_without_division(self):
        matcher = self.matcher([self.row(price_from_kzt=0)], use_llm=False)
        self.addCleanup(matcher.close)
        card = matcher.match(**{**self.query, "budget": 0})["cards"][0]
        self.assertEqual(card["match_facts"]["budget_difference"], 0)
        self.assertEqual(card["match_facts"]["budget"], 0)

    def test_invalid_requests(self):
        matcher = self.matcher([self.row()], use_llm=False)
        for changes in ({"budget": -1}, {"budget": float("nan")}, {"budget": float("inf")},
                        {"date": "2026-02-30"}, {"date": "20260926"}, {"city": " "},
                        {"duration": 0}, {"language": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                matcher.match(**{**self.query, **changes})

    def test_invalid_csv(self):
        for rows in ([self.row(), self.row()], [self.row(price_from_kzt="")],
                     [self.row(busy_dates="invalid")], [self.row(categories="|")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.matcher(rows)

    def test_llm_sees_only_top_three_and_cannot_reorder(self):
        client = Mock()
        content = json.dumps({"explanations": [
            {"id": i, "evidence_quote": f"Проводит церемонии по сценарию {i}."} for i in "CBA"]})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))])
        result = self.matcher([self.row(i) for i in "DCBA"], client=client).match(**self.query)
        self.assertEqual([c["id"] for c in result["cards"]], list("ABC"))
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "gpt-4o-mini")
        self.assertEqual(call["temperature"], 0.0)
        self.assertEqual([p["id"] for p in json.loads(call["messages"][-1]["content"])["profiles"]], list("ABC"))
        self.assertNotIn("warning", result)

    def test_api_failure_keeps_cards(self):
        client = Mock()
        client.chat.completions.create.side_effect = TimeoutError("secret error details")
        result = self.matcher([self.row()], client=client).match(**self.query)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["cards"][0]["explanation_source"], "python")
        self.assertNotIn("secret", result["warning"])

    def test_malformed_llm_response_falls_back(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"explanations": []}'))])
        result = self.matcher([self.row()], client=client).match(**self.query)
        self.assertEqual(result["cards"][0]["explanation_source"], "python")

    def test_real_dataset_scenarios(self):
        matcher = EventMatcher(DEFAULT_CSV, use_llm=False)
        query = {**self.query, "budget": 2000000, "language": None, "event_type": "корпоратив"}
        self.assertEqual(len(matcher.match(**query)["cards"]), 3)
        rare = matcher.match(**{**query, "category": "Флорист", "event_type": "свадьба"})
        self.assertIn(len(rare["cards"]), (1, 2))
        self.assertEqual(matcher.match(**{**query, "budget": 1})["status"], "no_matches")

    def test_budget_advice_checks_other_conditions(self):
        client = Mock()
        matcher = self.matcher([
            self.row("cheap_busy", price_from_kzt=350000, busy_dates=self.query["date"]),
            self.row("available", price_from_kzt=700000),
            self.row("wrong_language", price_from_kzt=500000, languages="английский"),
        ], client=client)
        result = matcher.match(**self.query)
        budget = next(item for item in result["suggestions"] if item["field"] == "budget")
        self.assertEqual(budget["value"], 700000)
        self.assertEqual(budget["candidate_ids"], ["available"])
        self.assertEqual(client.mock_calls, [])

    def test_no_false_advice_when_two_changes_needed(self):
        result = self.matcher([self.row(price_from_kzt=700000, languages="английский")],
                              use_llm=False).match(**self.query)
        self.assertEqual(result["suggestions"], [])
        self.assertIn("несколько условий", result["message"])

    def test_advice_is_reproducible_by_matching(self):
        rows = [self.row("budget", price_from_kzt=400000),
                self.row("date", busy_dates="2026-09-26|2026-09-27"),
                self.row("language", languages="английский"),
                self.row("format", event_formats="той"), self.row("duration", max_hours=2)]
        matcher = self.matcher(rows, use_llm=False)
        query = {**self.query, "duration": 4}
        result = matcher.match(**query)
        self.assertEqual({s["field"] for s in result["suggestions"]},
                         {"budget", "date", "language", "event_type", "duration"})
        for suggestion in result["suggestions"]:
            with self.subTest(field=suggestion["field"]):
                changed = matcher.match(**{**query, suggestion["field"]: suggestion["value"]})
                self.assertEqual(changed["eligible_count"], suggestion["candidate_count"])
                self.assertEqual(sorted(c["id"] for c in changed["cards"]), suggestion["candidate_ids"])
        self.assertEqual(next(s["value"] for s in result["suggestions"] if s["field"] == "date"),
                         "2026-09-28")

    def test_unknown_duration_is_not_promised(self):
        result = self.matcher([self.row(max_hours="")], use_llm=False).match(**self.query, duration=4)
        self.assertFalse(any(s["field"] == "duration" for s in result["suggestions"]))

    def test_date_suggestions_respect_horizon(self):
        from datetime import date, timedelta
        busy = "|".join((date(2026, 9, 26) + timedelta(days=i)).isoformat() for i in range(15))
        result = self.matcher([self.row(busy_dates=busy)], use_llm=False).match(**self.query)
        self.assertEqual(result["suggestions"], [])

    def test_invalid_quote_falls_back_only_for_affected_card(self):
        client = Mock()
        content = json.dumps({"explanations": [
            {"id": "A", "evidence_quote": "Получил премию за 1000 мероприятий."},
            {"id": "B", "evidence_quote": "Проводит церемонии по сценарию B."}]})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))])
        result = self.matcher([self.row("A"), self.row("B")], client=client).match(**self.query)
        self.assertEqual([c["explanation_source"] for c in result["cards"]], ["python", "openai"])
        self.assertNotIn("премию", str(result))
        for card in result["cards"]:
            self.assertIn(card["evidence"]["quote"].rstrip("."), card["explanation"])

    def test_extra_llm_claim_is_not_displayed(self):
        client = Mock()
        content = json.dumps({"explanations": [{"id": "A",
            "evidence_quote": "Проводит церемонии по сценарию A.", "text": "Бронь подтверждена."}]})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))])
        result = self.matcher([self.row()], client=client).match(**self.query)
        self.assertNotIn("Бронь подтверждена", str(result))
        self.assertEqual(result["cards"][0]["explanation_source"], "python")

    def test_missing_description_does_not_invent_experience(self):
        result = self.matcher([self.row(description="")], use_llm=False).match(**self.query)
        self.assertIsNone(result["cards"][0]["evidence"])
        self.assertNotIn("В описании", result["cards"][0]["explanation"])

    def test_fallback_prefers_specific_fact_over_shared_intro(self):
        result = self.matcher([
            self.row("A", description="Проводит мероприятия в Алматы. Работал на форуме с 3000 гостями."),
            self.row("B", description="Проводит мероприятия в Алматы. Ведёт камерные церемонии на природе.")
        ], use_llm=False).match(**self.query)
        quotes = [c["evidence"]["quote"] for c in result["cards"]]
        self.assertIn("3000", quotes[0])
        self.assertIn("на природе", quotes[1])

    def test_suggestions_order_does_not_depend_on_csv_order(self):
        rows = [self.row("B", languages="английский"), self.row("A", languages="казахский")]
        first = self.matcher(rows, use_llm=False).match(**self.query)
        second = self.matcher(list(reversed(rows)), use_llm=False).match(**self.query)
        self.assertEqual(first["suggestions"], second["suggestions"])


if __name__ == "__main__":
    unittest.main()
