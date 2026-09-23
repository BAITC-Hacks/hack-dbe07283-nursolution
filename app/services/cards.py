"""Сборка карточек: проверенные факты отдельно от текста и оформления.

Вызывается только для прошедших строгие фильтры профилей. Браузер получает
числа и условия, а не извлекает их из сгенерированного объяснения.
"""
from app.domain.models import Contractor


def build_card(profile: Contractor, request: dict, explanation: dict) -> dict:
    return dict(
        id=profile.id, anon_name=profile.anon_name, category=request["category"],
        categories=list(profile.categories), city=profile.city,
        price_from_kzt=profile.price_from_kzt, **explanation,
        match_facts=dict(
            event_type=request["event_type"],
            budget=request["budget"],
            budget_difference=request["budget"] - profile.price_from_kzt,
            date=request["date"],
            date_status="not_marked_busy",
            language=request["language"].strip() if request["language"] else None,
            duration=request["duration"],
            max_hours=profile.max_hours,
        ),
    )
