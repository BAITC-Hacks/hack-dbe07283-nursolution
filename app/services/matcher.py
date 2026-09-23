"""Правила фильтрации, советы и детерминированное ранжирование."""
from __future__ import annotations
import asyncio
from datetime import date as Date, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from app.config import DEFAULT_CSV, Settings
from app.domain.models import Contractor
from app.domain.validation import normalized, contains, number, iso_date, money
from app.repositories.source import CsvCatalog, Catalog
from app.services.explanations import ExplanationService
from app.services.cards import build_card

REASONS = ("city", "category", "budget", "date", "event_type", "language", "duration", "duration_unknown")

class EventMatcher:
    def __init__(self, csv_path: str | Path = DEFAULT_CSV, *, client: Any = None,
                 use_llm: bool = True, settings: Settings | None = None, repository: Catalog | None = None):
        self.repository = repository if repository is not None else CsvCatalog(csv_path)
        self.settings = settings or Settings.from_env()
        self.explanations = ExplanationService(client=client, settings=self.settings)
        self.use_llm = use_llm

    @property
    def contractors(self):
        return self.repository.load()

    def close(self):
        self.explanations.close()

    def match(self, city, date, event_type, category, budget, language=None, *, duration=None):
        """Синхронный интерфейс для CLI и интеграций; тот же дедлайн, что у API."""
        deadline = monotonic() + self.settings.request_timeout
        result, selected, request = self._prepare(city, date, event_type, category, budget, language, duration=duration)
        if not selected:
            return result
        explanations, warning = self.explanations.explain(selected, request, deadline, self.use_llm)
        return self._finish(result, selected, request, explanations, warning)

    async def amatch(self, *, deadline=None, **query):
        """Асинхронное ожидание LLM без занятия HTTP thread pool."""
        deadline = min(deadline if deadline is not None else float("inf"), monotonic() + self.settings.request_timeout)
        result, selected, request = await asyncio.to_thread(self._prepare, **query)
        if not selected:
            return result
        explanations, warning = await self.explanations.aexplain(selected, request, deadline, self.use_llm)
        return self._finish(result, selected, request, explanations, warning)

    @staticmethod
    def _finish(result, selected, request, explanations, warning):
        summary = result.pop("_summary", "")
        # Этап 4: модель не может менять состав и порядок карточек.
        for profile in selected:
            result["cards"].append(build_card(profile, request, explanations[profile.id]))
        result["message"] = f"Подобрали: {len(selected)}; всего проходят условия: {result['eligible_count']}."
        if len(selected) < 3:
            result["message"] += (f" Меньше трёх: число профилей в городе в этой категории — {result['scope_count']}. "
                                  + (summary or "Все доступные профили подходят."))
        if warning:
            result["warning"] = warning
        return result


    def _prepare(self, city: str, date: str, event_type: str, category: str,
              budget: float, language: str | None = None, *,
              duration: float | None = None) -> tuple[dict, list[Contractor], dict]:
        """Подготовить результат, TOP-3 и проверенный запрос без сетевых операций.

        status: matched / no_category_in_city / no_matches.
        duration — часы; неизвестный max_hours не подтверждает длительность.
        Цена «от» проверяется как нижняя граница, не как окончательная смета.
        """
        for key, value in (("city", city), ("event_type", event_type), ("category", category)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key}: требуется непустая строка")
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise ValueError("language: требуется непустая строка или None")
        date = iso_date(date)
        budget = number(budget, "budget")
        if duration is not None:
            duration = number(duration, "duration", positive=True)
        request = dict(city=city.strip(), date=date, event_type=event_type.strip(),
                       category=category.strip(), budget=budget, language=language, duration=duration)

        # Этап 1: только Python; один профиль — одна причина отказа.
        candidates, scoped, over_budget = [], [], []
        counts = dict.fromkeys(REASONS, 0)
        profiles = self.contractors
        for profile in profiles:
            if normalized(profile.city) != normalized(city):
                counts["city"] += 1
                continue
            if not contains(profile.categories, category):
                counts["category"] += 1
                continue
            scoped.append(profile)
            failures = self._failures(profile, request)
            reason = failures[0] if failures else None
            if reason == "budget":
                over_budget.append(profile.price_from_kzt)
            if reason:
                counts[reason] += 1
            else:
                candidates.append(profile)

        result = dict(status="matched", cards=[], message="", total_profiles=len(profiles),
                      scope_count=len(scoped), eligible_count=len(candidates), rejection_counts=counts,
                      suggestions=[])
        summary = self._rejection_summary(counts, over_budget)
        # Этап 2: ранний возврат, даже создание клиента здесь запрещено.
        if not scoped:
            result.update(status="no_category_in_city",
                          message=f"В городе {city.strip()} категория «{category.strip()}» отсутствует в каталоге.")
            return result, [], request
        if not candidates:
            result["suggestions"] = self._suggestions(scoped, request)
            advice = " ".join(item["message"] for item in result["suggestions"])
            if not advice:
                advice = ("Проверенные одиночные изменения бюджета, формата, языка, длительности "
                          "и даты в ближайшие 14 дней не дают кандидатов; нужно пересмотреть "
                          "несколько условий или уточнить данные профилей.")
            result.update(status="no_matches", message=(
                f"В городе {city.strip()} в категории «{category.strip()}» найдено профилей: {len(scoped)}. "
                f"Ни один не проходит по условиям. {summary} {advice}"))
            return result, [], request

        result["_summary"] = summary
        # Этап 3: язык оставлен явным ключом; при строгом фильтре он равен у всех.
        selected = sorted(candidates, key=lambda p: (
            budget - p.price_from_kzt,
            -int(language is not None and contains(p.languages, language)), p.id))[:3]
        return result, selected, request

    @staticmethod
    def _failures(profile: Contractor, request: dict) -> list[str]:
        """Все нарушения условий внутри выбранных города и категории.

        Один предикат используется и основным поиском, и проверкой советов.
        """
        checks = [
            ("budget", profile.price_from_kzt > request["budget"]),
            ("date", request["date"] in profile.busy_dates),
            ("event_type", not contains(profile.event_formats, request["event_type"])),
            ("language", request["language"] is not None and
             not contains(profile.languages, request["language"])),
        ]
        if request["duration"] is not None:
            checks.append(("duration_unknown", profile.max_hours is None))
            checks.append(("duration", profile.max_hours is not None and
                           request["duration"] > profile.max_hours))
        return [key for key, failed in checks if failed]

    def _suggestions(self, scoped: list[Contractor], request: dict) -> list[dict]:
        """Проверенные изменения ровно одного поля; без LLM и расширения каталога.

        Бюджет — минимально достаточный, дата — ближайшая последующая в пределах
        14 дней. Формат/язык — максимум кандидатов, длительность — наибольшая
        допустимая. Возвращается максимум один совет на поле, без применения.
        """
        values = {
            "budget": sorted({p.price_from_kzt for p in scoped if p.price_from_kzt > request["budget"]}),
            "date": [(Date.fromisoformat(request["date"]) + timedelta(days=offset)).isoformat()
                     for offset in range(1, min(14, (Date.max - Date.fromisoformat(request["date"])).days) + 1)],
            "event_type": sorted({v for p in scoped for v in p.event_formats}),
            "language": sorted({v for p in scoped for v in p.languages}) if request["language"] else [],
            "duration": sorted({p.max_hours for p in scoped if p.max_hours is not None and
                                request["duration"] is not None and p.max_hours < request["duration"]}, reverse=True),
        }
        labels = {"budget": "бюджет", "date": "дату", "event_type": "формат",
                  "language": "язык", "duration": "длительность"}
        suggestions = []
        for field, alternatives in values.items():
            options = []
            for value in alternatives:
                if normalized(str(value)) == normalized(str(request[field])):
                    continue
                changed = {**request, field: value}
                ids = sorted(p.id for p in scoped if not self._failures(p, changed))
                if ids:
                    options.append((value, ids))
            if not options:
                continue
            if field in ("language", "event_type"):
                options.sort(key=lambda option: (-len(option[1]), normalized(option[0]), option[0]))
            value, ids = options[0]
            display = f"{money(value)} ₸" if field == "budget" else f"{value:g} ч" if field == "duration" else str(value)
            suggestions.append(dict(
                field=field, value=value, candidate_count=len(ids), candidate_ids=ids,
                message=f"Если изменить только {labels[field]} на «{display}», "
                        f"всем условиям будут соответствовать профили: {len(ids)} (по данным каталога)."))
        return suggestions

    @staticmethod
    def _rejection_summary(counts: dict, prices: list[int]) -> str:
        labels = {
            "budget": "цена «от» выше бюджета", "date": "заняты на указанную дату",
            "event_type": "не работают в выбранном формате", "language": "нет выбранного языка",
            "duration": "максимальная длительность меньше запрошенной",
            "duration_unknown": "длительность не указана, подтвердить соответствие нельзя",
        }
        parts = [f"{labels[key]} — {counts[key]}" for key in labels if counts[key]]
        if not parts:
            return ""
        text = "Причины отказа (первая для каждого профиля): " + "; ".join(parts) + "."
        if prices:
            text += f" У отклонённых по бюджету цены начинаются от {money(min(prices))} ₸."
        if counts["duration_unknown"]:
            text += " Уточните допустимую длительность у подрядчиков."
        return text

