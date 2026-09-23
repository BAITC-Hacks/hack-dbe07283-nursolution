/* Framework-free UI. All profile/API content is rendered as text, never HTML. */
"use strict";

const form = document.querySelector("#order-form");
const results = document.querySelector("#results");
const panel = document.querySelector("#results-panel");
const context = document.querySelector("#results-context");
const note = document.querySelector("#results-note");
const submit = document.querySelector("#submit-button");
const submitLabel = document.querySelector("#submit-label");
const statusLive = document.querySelector("#status-live");
const numberFormat = new Intl.NumberFormat("ru-RU");
const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
let catalogReady = false;
let lastQuery = null;
let activeRequest = null;
let requestVersion = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function plural(n, one, few, many) {
  const v = n % 100;
  return v >= 11 && v <= 14 ? many : n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
}

function niceDate(value) {
  return dateFormat.format(new Date(`${value}T12:00:00`));
}

function capitalized(value) { return value.charAt(0).toUpperCase() + value.slice(1); }

function setBusy(busy) {
  panel.setAttribute("aria-busy", String(busy));
  submit.disabled = busy || !catalogReady;
  submitLabel.textContent = busy ? "Подбираем…" : "Подобрать людей";
}

function clearErrors() {
  document.querySelectorAll(".field-error").forEach(node => { node.textContent = ""; });
  form.querySelectorAll("[aria-invalid]").forEach(node => node.removeAttribute("aria-invalid"));
  document.querySelector("#form-error").hidden = true;
}

function fieldError(name, message) {
  const input = form.elements.namedItem(name);
  const label = document.getElementById(`${name}-error`);
  if (input && label) {
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", label.id);
    label.textContent = message;
    if (["language", "duration"].includes(name)) document.querySelector("#extra-options").open = true;
  } else {
    const error = document.querySelector("#form-error");
    error.textContent = message;
    error.hidden = false;
  }
}

function readQuery() {
  clearErrors();
  const values = Object.fromEntries(new FormData(form));
  const budgetText = values.budget.replace(/\s/g, "");
  let valid = true;
  if (!/^\d+(?:[.,]\d{1,2})?$/.test(budgetText) || !Number.isFinite(Number(budgetText.replace(",", ".")))) {
    fieldError("budget", "Укажите бюджет в тенге, например 500 000."); valid = false;
  }
  if (!values.date || !form.elements.date.validity.valid) {
    fieldError("date", "Выберите дату мероприятия."); valid = false;
  }
  for (const key of ["city", "event_type", "category"]) {
    if (!values[key]) { fieldError(key, "Выберите значение."); valid = false; }
  }
  if (form.elements.duration.validity.badInput || (values.duration && (!Number.isFinite(Number(values.duration)) || Number(values.duration) <= 0))) {
    fieldError("duration", "Укажите длительность больше нуля."); valid = false;
  }
  if (!valid) {
    form.querySelector("[aria-invalid=true]")?.focus();
    return null;
  }
  return {city: values.city, date: values.date, event_type: values.event_type,
    category: values.category, budget: Number(budgetText.replace(",", ".")),
    language: values.language || null, duration: values.duration ? Number(values.duration) : null};
}

function renderLoading(query) {
  results.replaceChildren(); note.hidden = true;
  context.classList.remove("pending-banner");
  context.textContent = query ? `${query.city} · ${niceDate(query.date)} · Проверяем условия` : "Загружаем каталог";
  document.querySelector("#results-count").textContent = "…";
  for (let i = 0; i < 3; i++) {
    const card = element("div", "loading-card");
    card.setAttribute("aria-hidden", "true");
    for (let j = 0; j < 4; j++) card.append(element("div", "loading-bar"));
    results.append(card);
  }
  statusLive.textContent = "Подбираем подрядчиков по вашим условиям.";
}

function renderCard(card, index, query) {
  const article = element("article", "contractor-card");
  const top = element("div", "card-top");
  const identity = element("div", "card-identity");
  identity.append(element("h3", "", card.anon_name), element("p", "card-meta", `${card.category} · ${card.city}`));
  const price = element("div", "card-price");
  price.append(element("small", "", "от "), document.createTextNode(`${numberFormat.format(card.price_from_kzt)} ₸`), element("small", "price-unit", "за мероприятие"));
  top.append(element("span", "card-number", String(index + 1).padStart(2, "0")), identity, price);
  const explanation = element("div", "explanation-block");
  const label = element("p", "why-label");
  label.innerHTML = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3 8 3 3 7-7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  label.append(document.createTextNode("Почему в подборке"));
  explanation.append(label, element("p", "explanation", card.explanation));
  article.append(top, explanation);
  return article;
}

function rejectionText(result) {
  const labels = {budget: "выше бюджета", date: "заняты на эту дату", event_type: "не работают в выбранном формате",
    language: "не указан нужный язык", duration: "не подходят по длительности", duration_unknown: "длительность не указана"};
  return Object.entries(labels).filter(([key]) => result.rejection_counts[key]).map(([key, label]) => `${result.rejection_counts[key]} — ${label}`).join("; ");
}

function suggestionLabel(suggestion) {
  if (suggestion.field === "budget") return `Бюджет ${numberFormat.format(suggestion.value)} ₸`;
  if (suggestion.field === "date") return `Перенести на ${niceDate(suggestion.value)}`;
  if (suggestion.field === "duration") return `Длительность ${suggestion.value} ч`;
  return `${suggestion.field === "language" ? "Язык" : "Формат"}: ${suggestion.value}`;
}

function populateForm(query) {
  for (const [key, value] of Object.entries(query)) {
    form.elements.namedItem(key).value = value === null ? "" : key === "budget" ? numberFormat.format(value) : value;
  }
  if (query.language || query.duration) document.querySelector("#extra-options").open = true;
  updatePresets();
}

function renderResponse(result, query) {
  results.replaceChildren(); note.hidden = true;
  context.classList.remove("pending-banner");
  context.textContent = `${query.city} · ${niceDate(query.date)} · ${capitalized(query.event_type)}`;
  const count = result.cards.length;
  document.querySelector("#results-count").textContent = `${count} ${plural(count, "совпадение", "совпадения", "совпадений")}`;
  if (result.status === "matched") {
    result.cards.forEach((card, index) => results.append(renderCard(card, index, query)));
    const notes = [];
    if (count < 3) notes.push(`Подош${count === 1 ? "ёл только один подрядчик" : "ли только два подрядчика"}. ${rejectionText(result) ? `Остальные: ${rejectionText(result)}.` : "Это все профили в выбранной категории и городе."}`);
    notes.push("Указаны цены «от». Итоговую стоимость и свободную дату уточните у подрядчика.");
    note.textContent = notes.join(" "); note.hidden = false;
    statusLive.textContent = `Подборка готова. Найдено: ${count}.`;
    return;
  }
  const empty = element("div", "empty-state");
  empty.append(element("div", "empty-mark", "0 /"));
  if (result.status === "no_category_in_city") {
    empty.append(element("h3", "", "Пока нет в каталоге"), element("p", "", `В городе ${query.city} пока нет подрядчиков категории «${query.category}». Выберите другую категорию или город.`));
    const change = element("button", "retry-button", "Изменить категорию ↗"); change.type = "button";
    change.addEventListener("click", () => form.elements.category.focus()); empty.append(change);
  } else {
    empty.append(element("h3", "", "Немного изменим условия?"), element("p", "", `В городе ${query.city} есть профили в категории «${query.category}»: ${result.scope_count}. По всем условиям пока никто не подходит.`), element("p", "", `${capitalized(rejectionText(result))}.`));
    if (result.suggestions.length) {
      const suggestions = element("div", "suggestions");
      result.suggestions.forEach(suggestion => {
        const button = element("button", "suggestion-button", suggestionLabel(suggestion)); button.type = "button";
        button.append(element("small", "", `${suggestion.candidate_count} ${plural(suggestion.candidate_count, "подходящий профиль", "подходящих профиля", "подходящих профилей")} · остальные условия те же`));
        button.addEventListener("click", () => { populateForm({...query, [suggestion.field]: suggestion.value}); runMatch(true); });
        suggestions.append(button);
      }); empty.append(suggestions);
    } else {
      empty.append(element("p", "", "Одного изменения недостаточно. Попробуйте пересмотреть несколько условий; ближайшие 14 дней мы уже проверили."));
    }
  }
  results.append(empty); statusLive.textContent = result.message;
}

function renderError(message, retry) {
  results.replaceChildren(); note.hidden = true;
  const empty = element("div", "empty-state");
  empty.append(element("div", "empty-mark", "—"), element("h3", "", "Не удалось получить подборку"), element("p", "", message));
  const button = element("button", "retry-button", "Попробовать ещё раз ↗"); button.type = "button";
  button.addEventListener("click", retry); empty.append(button); results.append(empty);
  context.textContent = "Ваши параметры сохранены в форме";
  document.querySelector("#results-count").textContent = "—";
  statusLive.textContent = message;
}

async function runMatch(scroll = false) {
  const query = readQuery(); if (!query) return;
  activeRequest?.abort(); const controller = new AbortController(); activeRequest = controller;
  const version = ++requestVersion;
  setBusy(true); renderLoading(query);
  if (scroll && window.matchMedia("(max-width: 760px)").matches) panel.scrollIntoView({behavior: "smooth", block: "start"});
  const timeout = setTimeout(() => controller.abort("timeout"), 12000);
  try {
    const response = await fetch("/match", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(query), signal: controller.signal});
    const result = await response.json();
    if (version !== requestVersion) return;
    if (!response.ok) {
      if (response.status === 422) {
        for (const item of result.error?.fields || []) fieldError(item.field, item.message);
        form.querySelector("[aria-invalid=true]")?.focus();
      }
      throw new Error(result.error?.message || "Сервис временно недоступен. Попробуйте ещё раз.");
    }
    lastQuery = query; renderResponse(result, query);
  } catch (error) {
    if (version !== requestVersion) return;
    renderError(controller.signal.reason === "timeout" ? "Подбор занял больше времени, чем ожидалось. Попробуйте повторить запрос." : error instanceof TypeError ? "Не получилось связаться с сервисом. Проверьте соединение и попробуйте снова." : error.message, () => runMatch());
  } finally {
    clearTimeout(timeout);
    if (version === requestVersion) { activeRequest = null; setBusy(false); }
  }
}

function updatePresets() {
  const value = Number(form.elements.budget.value.replace(/\s/g, ""));
  document.querySelectorAll("[data-budget]").forEach(button => {
    const active = Number(button.dataset.budget) === value;
    button.classList.toggle("is-active", active); button.setAttribute("aria-pressed", String(active));
  });
}

function changed() {
  clearErrors(); updatePresets();
  if (activeRequest) { ++requestVersion; activeRequest.abort(); activeRequest = null; setBusy(false); results.replaceChildren(); }
  if (lastQuery || catalogReady) {
    context.textContent = "Условия изменены — обновите подборку"; context.classList.add("pending-banner");
    results.querySelectorAll(".suggestion-button").forEach(button => { button.disabled = true; });
  }
}

async function initialize() {
  setBusy(true); renderLoading(null);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch("/catalog", {signal: controller.signal});
    if (!response.ok) throw new Error("Каталог временно недоступен.");
    const catalog = await response.json();
    const fields = {city: [catalog.cities, "Алматы"], event_type: [catalog.event_types, "корпоратив"], category: [catalog.categories, "Ведущий"], language: [catalog.languages, ""]};
    for (const [key, [values, preferred]] of Object.entries(fields)) {
      const select = form.elements.namedItem(key); select.replaceChildren();
      if (key === "language") select.add(new Option("Любой", ""));
      values.forEach(value => select.add(new Option(capitalized(value), value)));
      select.value = preferred; if (select.selectedIndex < 0) select.selectedIndex = 0;
      select.disabled = false;
    }
    document.querySelector("#catalog-meta").textContent = `${catalog.total_profiles} ${plural(catalog.total_profiles, "профиль", "профиля", "профилей")} в каталоге · Казахстан`;
    catalogReady = true; setBusy(false); await runMatch();
  } catch {
    renderError("Не удалось загрузить каталог. Проверьте, что сервис доступен, и попробуйте снова.", initialize);
    setBusy(false);
  } finally { clearTimeout(timeout); }
}

form.addEventListener("submit", event => { event.preventDefault(); runMatch(true); });
form.addEventListener("input", changed);
form.addEventListener("change", changed);
form.elements.budget.addEventListener("blur", () => {
  const raw = form.elements.budget.value.replace(/\s/g, "").replace(",", ".");
  if (/^\d+(?:\.\d{1,2})?$/.test(raw) && Number.isFinite(Number(raw))) form.elements.budget.value = numberFormat.format(Number(raw));
});
document.querySelectorAll("[data-budget]").forEach(button => button.addEventListener("click", () => {
  form.elements.budget.value = numberFormat.format(Number(button.dataset.budget)); changed();
}));
const dialog = document.querySelector("#about-dialog");
document.querySelector("#about-open").addEventListener("click", () => dialog.showModal());
document.querySelector("#about-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => { if (event.target === dialog) { const bounds = dialog.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close(); } });
initialize();
