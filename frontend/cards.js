/* Card presentation consumes verified facts. No parsing of LLM prose or HTML. */
import {element, numberFormat, niceDate, capitalized} from "./ui.js";

const money = value => `${numberFormat.format(value)} ₸`;

function fact(label, value) {
  const row = element("div", "detail-row");
  row.append(element("dt", "", label), element("dd", "", value));
  return row;
}

export function renderCard(card, index) {
  const article = element("article", "contractor-card");
  article.setAttribute("aria-labelledby", `contractor-${index}`);
  const top = element("div", "card-top");
  const identity = element("div", "card-identity");
  const heading = element("h3", "", card.anon_name);
  heading.id = `contractor-${index}`;
  identity.append(element("p", "card-meta", `${card.category} / ${card.city}`), heading);
  const avatar = element("span", "card-avatar", Array.from(card.anon_name.trim())[0] || "·");
  avatar.setAttribute("aria-hidden", "true");
  top.append(avatar, identity);

  const body = element("div", "card-body");
  const story = element("div", "card-story");
  story.append(element("span", "story-label", card.evidence ? "Чем выделяется · из профиля" : "По условиям заказа"));
  if (card.evidence) {
    story.append(element("blockquote", "card-quote", card.evidence.quote.replace(/[.;]+$/, "")));
  } else {
    story.append(element("p", "card-summary", card.explanation));
  }
  const pricing = element("div", "card-pricing");
  const price = element("p", "card-price");
  price.append(element("span", "price-from", "от "), document.createTextNode(money(card.price_from_kzt)));
  pricing.append(element("span", "story-label", "За мероприятие"), price);

  // Older API responses still show their explanation; structured details only
  // appear when supplied by the server, never inferred from prose.
  const facts = card.match_facts;
  if (facts) {
    pricing.append(element("p", "budget-fit", facts.budget_difference === 0
      ? "В пределах бюджета · ровно ваш лимит"
      : `В пределах бюджета · на ${money(facts.budget_difference)} ниже`));
  }
  body.append(story, pricing);
  article.append(top, body);

  if (facts) {
    const bottom = element("div", "card-bottom");
    const matches = element("ul", "match-tags");
    matches.setAttribute("aria-label", "Совпадения с запросом");
    [capitalized(facts.event_type), facts.language ? capitalized(facts.language) : null,
      facts.duration !== null ? `${numberFormat.format(facts.duration)} ч на площадке` : null]
      .filter(Boolean).forEach(value => matches.append(element("li", "match-tag", value)));
    bottom.append(matches);
    article.append(bottom);
    const details = element("details", "card-details");
    const summary = element("summary", "", "Условия и источник");
    summary.append(element("span", "details-sign", "+"));
    const list = element("dl", "detail-list");
    list.append(fact("Дата", `${niceDate(facts.date)} — нет среди занятых дат в каталоге`));
    list.append(fact("Бюджет", `От ${money(card.price_from_kzt)} при лимите ${money(facts.budget)}`));
    list.append(fact("Формат", capitalized(facts.event_type)));
    if (facts.language) list.append(fact("Язык", capitalized(facts.language)));
    if (facts.duration !== null) {
      list.append(fact("Длительность", `Нужно ${numberFormat.format(facts.duration)} ч · в профиле до ${numberFormat.format(facts.max_hours)} ч`));
    }
    details.append(summary, list);
    if (card.evidence) {
      details.append(element("p", "source-note", card.explanation_source === "openai"
        ? "Цитату выбрала OpenAI. Повторный ответ может быть взят из кеша."
        : "Цитата выбрана из каталога без обращения к AI."));
      details.append(element("p", "source-note", "Текст взят из описания подрядчика. Сведения об опыте указаны самим подрядчиком."));
    }
    details.append(element("p", "source-note", "Стоимость и возможность бронирования нужно подтвердить лично."));
    article.append(details);
  }
  return article;
}
