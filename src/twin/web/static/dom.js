const PROPERTY_KEYS = new Set(["value", "checked", "indeterminate", "selected"]);

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on") && typeof value === "function") {
        el.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "class") {
        el.className = Array.isArray(value) ? value.filter(Boolean).join(" ") : value;
      } else if (key === "dataset") {
        Object.assign(el.dataset, value);
      } else if (PROPERTY_KEYS.has(key)) {
        el[key] = value;
      } else {
        el.setAttribute(key, value === true ? "" : String(value));
      }
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

export function setChildren(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

export function paragraphs(text, className) {
  const blocks = String(text ?? "")
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  return blocks.map((block) => h("p", { class: className }, block));
}

export function pct(value, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "—";
}

export function num(value, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

export function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours} 小时 ${String(minutes).padStart(2, "0")} 分`;
  if (minutes) return `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒`;
  return `${seconds} 秒`;
}

export function parseServerTime(value) {
  if (!value) return null;
  const normalized = String(value).replace(/(\.\d{3})\d+/, "$1").replace(" ", "T");
  const time = Date.parse(normalized);
  return Number.isNaN(time) ? null : time;
}

export function formatDateTime(value) {
  const time = parseServerTime(value);
  if (time === null) return value ? String(value) : "—";
  const d = new Date(time);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function addDays(isoDate, days) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate || "");
  if (!match) return "";
  const d = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return d.toISOString().slice(0, 10);
}

export function badge(text, tone = "neutral") {
  return h("span", { class: `badge tone-${tone}` }, text);
}

export function loading(text = "正在加载…") {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), text);
}

export function empty(title, hint, link) {
  return h(
    "div",
    { class: "empty" },
    h("p", { class: "empty-title" }, title),
    hint ? h("p", { class: "muted" }, hint) : null,
    link ? h("p", { class: "empty-action" }, h("a", { href: link.href, class: "btn" }, link.text)) : null,
  );
}

export function field({ label, input, help, id }) {
  const helpId = help ? `${id}-help` : null;
  if (helpId) input.setAttribute("aria-describedby", helpId);
  input.id = id;
  return h(
    "div",
    { class: "field" },
    h("label", { for: id }, label),
    input,
    help ? h("p", { class: "help", id: helpId }, help) : null,
  );
}

export function checkbox({ label, checked, help, id }) {
  const input = h("input", { type: "checkbox", id, checked: Boolean(checked) });
  const helpId = help ? `${id}-help` : null;
  if (helpId) input.setAttribute("aria-describedby", helpId);
  const wrapper = h(
    "div",
    { class: "field field-check" },
    h("label", { class: "check", for: id }, input, h("span", null, label)),
    help ? h("p", { class: "help", id: helpId }, help) : null,
  );
  return { wrapper, input };
}

export function meter(value, label) {
  const ratio = typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const fill = h("div", { class: "meter-fill" });
  fill.style.width = `${(ratio * 100).toFixed(1)}%`;
  return h("div", { class: "meter", role: "img", "aria-label": `${label} ${num(value)}` }, fill);
}

export function pageHeader(title, lead) {
  return h(
    "header",
    { class: "page-head" },
    h("h1", { tabindex: "-1" }, title),
    lead ? h("p", { class: "lead" }, lead) : null,
  );
}

const SESSION_PREFIX = "twin.";

export function sessionGet(key) {
  try {
    const raw = window.sessionStorage.getItem(SESSION_PREFIX + key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

export function sessionSet(key, value) {
  try {
    if (value === null || value === undefined) window.sessionStorage.removeItem(SESSION_PREFIX + key);
    else window.sessionStorage.setItem(SESSION_PREFIX + key, JSON.stringify(value));
  } catch {
    /* storage unavailable: state lives only in memory */
  }
}

export function toast(message, tone = "info") {
  const region = document.getElementById("toasts");
  if (!region) return;
  const note = h("div", { class: `toast tone-${tone}` }, message);
  region.append(note);
  window.setTimeout(() => note.remove(), 4500);
}
