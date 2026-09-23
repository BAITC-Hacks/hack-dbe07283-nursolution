"""Проверяемые фрагменты и локальное построение объяснений."""
import re
from app.domain.models import Contractor
from app.domain.validation import normalized, money

def evidence_options(profile: Contractor, peers: list[Contractor]) -> list[str]:
    """Короткие дословные фрагменты, сначала отличающие профиль от соседей.

    Это сведения самого подрядчика, а не независимая проверка его опыта.
    Фрагменты с рекламными клише не используются даже в офлайн-режиме.
    """
    description = " ".join(profile.description.split())
    fragments = re.split(r"(?<=[.!?;])\s+|[•\n]+", description)
    fragments = [part.strip() for part in fragments if 20 <= len(part.strip()) <= 300
                 and not any(word in part.casefold() for word in (
                     "прекрасный выбор", "отличный выбор", "профессионал", "безупречн",
                     "лучший", "лучших", "идеальн", "харизм"))]
    other_descriptions = [normalized(p.description) for p in peers if p.id != profile.id]
    fragments = list(dict.fromkeys(fragments))
    fragments.sort(key=lambda part: (
        sum(normalized(part) in text for text in other_descriptions),
        -int(bool(re.search(r"\d", part))),
        description.find(part), part))
    return fragments[:6]

def render_explanation(profile: Contractor, request: dict, quote: str | None) -> str:
    """Свободные утверждения модели не попадают в карточку: только цитата и факты."""
    facts = (f"Цена от {money(profile.price_from_kzt)} ₸ при бюджете {money(request['budget'])} ₸; "
             f"формат «{request['event_type']}» указан, дата {request['date']} не отмечена занятой")
    if request["language"]:
        facts += f"; язык «{request['language']}» указан"
    if request["duration"] is not None:
        facts += f"; лимит {profile.max_hours:g} ч при запросе {request['duration']:g} ч"
    return (f"В описании указано: «{quote.rstrip('.;')}». " if quote else "") + facts + "."

