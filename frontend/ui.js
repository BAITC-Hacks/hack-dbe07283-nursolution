/* Small shared view helpers; API/profile values are always text nodes. */
export const numberFormat = new Intl.NumberFormat("ru-RU");
const dateFormat = new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "long"});

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function plural(n, one, few, many) {
  const value = n % 100;
  return value >= 11 && value <= 14 ? many : n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
}

export function niceDate(value) {
  return dateFormat.format(new Date(`${value}T12:00:00`));
}

export function capitalized(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
