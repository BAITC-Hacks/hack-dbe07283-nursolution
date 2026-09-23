/* Framework-free UI. All profile/API content is rendered as text, never HTML. */
import {element, numberFormat, plural, niceDate, capitalized} from "./ui.js";
import {renderCard} from "./cards.js";
import "./about.js";

const form = document.querySelector("#order-form");
const results = document.querySelector("#results");
const panel = document.querySelector("#results-panel");
const context = document.querySelector("#results-context");
const note = document.querySelector("#results-note");
const submit = document.querySelector("#submit-button");
const submitLabel = document.querySelector("#submit-label");
const statusLive = document.querySelector("#status-live");
const initialState = document.querySelector("#selection-start");
let catalogReady = false;
let lastQuery = null;
let activeRequest = null;
let requestVersion = 0;

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
  panel.hidden = false;
  panel.removeAttribute("data-stale");
  initialState.hidden = true;
  results.replaceChildren(); note.replaceChildren(); note.hidden = true;
  context.classList.remove("pending-banner");
  context.textContent = query ? `${query.city} · ${niceDate(query.date)} · Проверяем условия` : "Загружаем каталог";
  document.querySelector("#results-count").textContent = "…";
  document.querySelector("#results-title").textContent = "Ищем совпадения";
  for (let i = 0; i < 3; i++) {
    const card = element("div", "loading-card");
    card.setAttribute("aria-hidden", "true");
    for (let j = 0; j < 4; j++) card.append(element("div", "loading-bar"));
    results.append(card);
  }
  statusLive.textContent = "Подбираем подрядчиков по вашим условиям.";
}

function rejectionList(result) {
  const labels = {budget: "выше бюджета", date: "заняты на эту дату", event_type: "другой формат",
    language: "нет нужного языка", duration: "не подходят по длительности", duration_unknown: "длительность неизвестна"};
  const list = element("dl", "rejection-list");
  for (const [key, label] of Object.entries(labels)) {
    if (!result.rejection_counts[key]) continue;
    const item = element("div", "rejection-item");
    item.append(element("dt", "", label), element("dd", "", String(result.rejection_counts[key])));
    list.append(item);
  }
  return list;
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
  panel.removeAttribute("data-stale");
  results.replaceChildren(); note.replaceChildren(); note.hidden = true;
  context.classList.remove("pending-banner");
  context.textContent = `${query.city} · ${niceDate(query.date)} · ${capitalized(query.event_type)}`;
  const count = result.cards.length;
  document.querySelector("#results-title").textContent = count ? "Ваша подборка" : "Результат поиска";
  document.querySelector("#results-count").textContent = `${count} ${plural(count, "вариант", "варианта", "вариантов")}`;
  if (result.status === "matched") {
    result.cards.forEach((card, index) => results.append(renderCard(card, index)));
    if (count < 3) {
      const detail = element("details", "selection-note");
      const summary = element("summary", "", `Почему ${count === 1 ? "только один вариант" : "только два варианта"}?`);
      summary.append(element("span", "details-sign", "+"));
      detail.append(summary, element("p", "", `В этом городе и категории — ${result.scope_count} ${plural(result.scope_count, "профиль", "профиля", "профилей")}.`));
      const rejections = rejectionList(result);
      if (rejections.children.length) detail.append(rejections, element("p", "", "Для каждого профиля показана первая причина отказа."));
      else detail.append(element("p", "", "Все профили в выбранном городе и категории соответствуют условиям."));
      note.append(detail);
    }
    note.append(element("p", "booking-note", "Цена — ориентир, дата — по каталогу. Перед бронированием подтвердите детали с подрядчиком."));
    note.hidden = false;
    statusLive.textContent = `Подборка готова. Найдено: ${count}.`;
    return;
  }
  const empty = element("div", "empty-state");
  empty.append(element("div", "empty-mark", "Не совпало"));
  if (result.status === "no_category_in_city") {
    empty.append(element("h3", "", "Пока нет в каталоге"), element("p", "", `В городе ${query.city} пока нет подрядчиков категории «${query.category}». Выберите другую категорию или город.`));
    const change = element("button", "retry-button", "Изменить категорию ↗"); change.type = "button";
    change.addEventListener("click", () => form.elements.category.focus()); empty.append(change);
  } else {
    empty.append(element("h3", "", "Пока без точного совпадения"), element("p", "", `В городе ${query.city} есть профили в категории «${query.category}»: ${result.scope_count}. По всем условиям пока никто не подходит.`), rejectionList(result));
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
  panel.hidden = false;
  panel.removeAttribute("data-stale");
  initialState.hidden = true;
  results.replaceChildren(); note.replaceChildren(); note.hidden = true;
  const empty = element("div", "empty-state");
  empty.append(element("div", "empty-mark", "—"), element("h3", "", "Не удалось получить подборку"), element("p", "", message));
  const button = element("button", "retry-button", "Попробовать ещё раз ↗"); button.type = "button";
  button.addEventListener("click", retry); empty.append(button); results.append(empty);
  context.textContent = "Ваши параметры сохранены в форме";
  document.querySelector("#results-title").textContent = "Результат поиска";
  document.querySelector("#results-count").textContent = "—";
  statusLive.textContent = message;
}

async function runMatch(scroll = false) {
  const query = readQuery(); if (!query) return;
  activeRequest?.abort(); const controller = new AbortController(); activeRequest = controller;
  const version = ++requestVersion;
  setBusy(true); renderLoading(query);
  if (scroll) panel.scrollIntoView({behavior: "auto", block: "start"});
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
  if (activeRequest) {
    ++requestVersion; activeRequest.abort(); activeRequest = null; setBusy(false);
    results.replaceChildren(); panel.hidden = true; initialState.hidden = false;
    lastQuery = null;
  }
  if (lastQuery) {
    context.textContent = "Условия изменены — обновите подборку"; context.classList.add("pending-banner");
    panel.setAttribute("data-stale", "true");
    results.querySelectorAll(".suggestion-button").forEach(button => { button.disabled = true; });
  }
}

async function initialize() {
  setBusy(true);
  submitLabel.textContent = "Загружаем каталог…";
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
    const requestedCategory = new URLSearchParams(window.location.search).get("category");
    if (catalog.categories.includes(requestedCategory)) form.elements.category.value = requestedCategory;
    catalogReady = true; setBusy(false);
    panel.hidden = true; initialState.hidden = false;
    statusLive.textContent = "Каталог готов. Укажите условия и запустите подбор.";
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
initialize();
