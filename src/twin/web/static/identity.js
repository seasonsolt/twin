import { api, errorBox } from "./api.js";
import { badge, h, loading, pageHeader } from "./dom.js";
import { onStatus, state } from "./state.js";

function table(headers, rows) {
  return h("div", { class: "identity-table-wrap", tabindex: "0", role: "region", "aria-label": headers[0] },
    h("table", { class: "table" },
      h("thead", null, h("tr", null, headers.map((text) => h("th", { scope: "col" }, text)))),
      h("tbody", null, rows.map((cells) => h("tr", null, cells.map((cell) => h("td", null, cell))))),
    ),
  );
}

export async function identityPage({ root, scope }) {
  if (!scope.alive) return;
  const content = h("div");
  const label = h("p");
  const renderLabel = () => label.replaceChildren(state.status?.labels?.explicit ? badge(state.status.labels.explicit, "info") : "");
  renderLabel();
  scope.onDispose(onStatus(renderLabel));
  root.replaceChildren(pageHeader("身份", "名字、别名、预置音色与形象来自配置，只读展示。"), label, content);
  root.querySelector("h1")?.focus({ preventScroll: true });

  async function load() {
    content.replaceChildren(loading());
    try {
      const data = await api("/api/identity");
      if (!scope.alive) return;
      content.replaceChildren(
        h("section", { class: "card" }, h("h2", null, "名字与音色/形象"),
          h("p", null, `名字：${data.name}`),
          h("p", null, `别名：${data.aliases.join("、") || "—"}`),
          h("p", null, `音色：${data.voice || "—"}（预置音色）`),
          h("p", null, `形象：${data.avatar || "—"}（风格化插画）`),
        ),
        h("section", { class: "card" }, h("h2", null, "出境"),
          h("p", { class: "muted" }, "外部服务按配置使用，以下如实展示各后端的出境分类。"),
          table(["类型", "提供方", "主机", "本机/外部", "声明/推断"], data.egress.map((row, index) => [
            index < 4 ? row.kind : `llm（评委 ${index - 3}）`, row.provider, row.host || "未知",
            badge(row.external ? "外部" : "本机", row.external ? "hold" : "neutral"), row.declared ? "声明" : "推断",
          ])),
        ),
        h("p", { class: "muted" }, "本版本不支持真人声音复刻或照片驱动形象。"),
      );
    } catch (err) {
      if (scope.alive) content.replaceChildren(errorBox(err, { retry: load }));
    }
  }

  await load();
}
