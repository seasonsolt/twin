import { describeError, errorBox } from "./api.js";
import { h } from "./dom.js";
import { personaChatPage, personaProfilePage, personaQuestionnairePage, personaSourcesPage } from "./persona.js";
import { closePlayback } from "./playback.js";
import { createScope, onStatus, refreshStatus, state } from "./state.js";

const DEFAULT_ROUTE = "chat";

const ROUTES = {
  chat: { title: "和分身聊天", render: personaChatPage },
  questionnaire: { title: "建档问卷", render: personaQuestionnairePage },
  persona: { title: "人格档案", render: personaProfilePage },
  sources: { title: "资料与构建", render: personaSourcesPage },
};

let currentScope = null;
let firstRoute = true;

function safeDecode(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const cut = raw.indexOf("?");
  const path = cut === -1 ? raw : raw.slice(0, cut);
  const search = cut === -1 ? "" : raw.slice(cut + 1);
  return {
    segments: path.split("/").filter(Boolean).map(safeDecode),
    query: new URLSearchParams(search),
  };
}

function setActiveNav(name) {
  for (const link of document.querySelectorAll("[data-route]")) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

async function route() {
  closePlayback();
  const { segments, query } = parseHash();
  const name = segments[0] || DEFAULT_ROUTE;
  const entry = ROUTES[name];
  if (!entry) {
    window.location.replace(`#/${DEFAULT_ROUTE}`);
    return;
  }
  if (currentScope) currentScope.dispose();
  const scope = createScope();
  currentScope = scope;
  setActiveNav(name);
  document.title = `${entry.title} · 数字分身`;

  const view = document.getElementById("view");
  view.replaceChildren();
  const ctx = { root: view, segments: segments.slice(1), query, scope, focused: false };
  const isFirst = firstRoute;
  firstRoute = false;
  if (!isFirst) window.scrollTo(0, 0);

  const rendering = entry.render(ctx);
  if (!isFirst && !ctx.focused) view.querySelector("h1")?.focus({ preventScroll: true });
  try {
    await rendering;
  } catch (err) {
    if (scope.alive) view.replaceChildren(errorBox(err, { retry: route }));
  }
}

function chip(label, value, title, warn = false) {
  return h(
    "span",
    { class: ["chip", warn && "chip-warn"], title },
    h("span", { class: "chip-label" }, label),
    h("span", null, value),
  );
}

function renderStatus() {
  const bar = document.getElementById("statusbar");
  const target = document.getElementById("target-name");
  if (!bar || !target) return;
  const status = state.status;
  if (!status) {
    if (state.statusError) {
      const info = describeError(state.statusError);
      bar.replaceChildren(
        h("span", { class: "status-error" }, `无法读取资料库概况：${info.title}。${info.hint}`),
        h("button", { type: "button", class: "btn small", onclick: () => refreshStatus() }, "重试"),
      );
    }
    return;
  }
  target.textContent = status.target_name ? `目标人物：${status.target_name}` : "";
  const footer = document.getElementById("footer-note");
  if (footer && status.target_name) {
    footer.textContent = `所有推演结果均为模拟，供个人使用参考，不代表${status.target_name}本人的意见或决定。数据只保存在本机。`;
  }
  const counts = status.counts || {};
  const llm = status.llm || {};
  const backendError = llm.error || status.embed?.error;
  bar.replaceChildren(
    chip("资料", `${counts.sources ?? 0} 份`),
    chip("人格条目", `${counts.items ?? 0} 条`),
    backendError
      ? chip("模型", "配置有误，推演、构建和评测暂不可用", String(backendError), true)
      : chip("模型", [llm.provider, llm.model].filter(Boolean).join(" · ") || "未配置"),
  );
  const external = (status.egress || []).filter((entry) => entry.external);
  if (external.length) bar.append(h("span", { class: "status-error" }, `出境（外部服务）：${external.map((entry) => `${entry.kind}/${entry.provider} ${entry.host || "未知主机"}（${entry.granted ? "已授权" : "未授权"}）`).join("；")}`));
}

function boot() {
  const skip = document.querySelector(".skip-link");
  skip?.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("main")?.focus();
  });
  onStatus(renderStatus);
  window.addEventListener("hashchange", route);
  refreshStatus().finally(route);
}

boot();
