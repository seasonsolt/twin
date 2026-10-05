import { api, errorBox } from "./api.js";
import { badge, h, loading, pageHeader, toast } from "./dom.js";
import { onStatus, refreshStatus, state } from "./state.js";

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
  const hint = h("div", { role: "status", "aria-live": "polite" });
  const label = h("p");
  const renderLabel = () => label.replaceChildren(state.status?.labels?.explicit ? badge(state.status.labels.explicit, "info") : "");
  renderLabel();
  scope.onDispose(onStatus(renderLabel));
  root.replaceChildren(pageHeader("身份与授权", "授权记录只追加，不删除历史。名字、别名与预置音色来自配置。"), label, hint, content);
  root.querySelector("h1")?.focus({ preventScroll: true });
  let data;
  let busy = false;

  function controls(consentScope) {
    return h("div", { class: "btn-row" }, ["grant", "revoke"].map((decision) =>
      h("button", {
        type: "button", class: "btn small", dataset: { consent: consentScope },
        "aria-label": `${decision === "grant" ? "授权" : "撤回"} ${consentScope}`,
        onclick: () => change(consentScope, decision),
      }, decision === "grant" ? "授权" : "撤回"),
    ));
  }

  async function change(consentScope, decision) {
    if (busy || !scope.alive) return;
    if (decision === "revoke" && !window.confirm(`确定撤回 ${consentScope}？历史记录将保留。`)) return;
    if (decision === "grant" && consentScope.startsWith("egress:")) {
      const hosts = [...new Set(data.egress.filter((row) => row.external && `egress:${row.kind}` === consentScope).map((row) => row.host || "未知主机"))];
      if (!window.confirm(`授权 ${consentScope} 后，数据将发送到外部主机：${hosts.join("、")}。此许可适用于同类型的所有后端（包括评委）。确定授权？`)) return;
    }
    busy = true;
    content.querySelectorAll("button[data-consent]").forEach((button) => { button.disabled = true; });
    try {
      const result = await api("/api/identity/consent", { method: "POST", json: { scope: consentScope, decision } });
      if (!scope.alive) return;
      hint.replaceChildren(h("div", { class: "callout tone-info" },
        h("p", null, result.message),
        result.rebuild_needed ? h("a", { class: "btn small", href: "#/sources" }, "前往资料与构建，重建人格档案") : null,
      ));
      toast(result.message.split("\n")[0], "go");
      await Promise.all([load(), refreshStatus()]);
    } catch (err) {
      if (scope.alive) hint.replaceChildren(errorBox(err));
    } finally {
      busy = false;
      if (scope.alive) content.querySelectorAll("button[data-consent]").forEach((button) => { button.disabled = false; });
    }
  }

  async function load() {
    content.replaceChildren(loading());
    try {
      const next = await api("/api/identity");
      if (!scope.alive) return;
      data = next;
      const facets = data.consents.filter((row) => row.scope.startsWith("facet:"));
      content.replaceChildren(
        h("section", { class: "card" }, h("h2", null, "名字与音色"),
          h("p", null, `名字：${data.name}`),
          h("p", null, `别名：${data.aliases.join("、") || "—"}`),
          h("p", null, `音色：${data.voice || "—"}（预置音色）`),
          h("p", null, `形象：${data.avatar || "—"}（风格化插画，不使用照片）`),
        ),
        h("section", { class: "card" }, h("h2", null, "细项授权"),
          h("p", { class: "muted" }, "未记录的细项沿用问卷推导；变更后需要重建人格档案。时间为 UTC。"),
          table(["细项", "最新决定", "时间（UTC）", "来源", "操作"], facets.map((row) => [
            `${row.scope} ${row.name}`,
            h("span", null, badge(row.label, row.granted ? "go" : "neutral"), row.derived_decision ? `（按问卷推导：${row.granted ? "已授权" : "未授权"}）` : ""),
            row.at || "—", row.origin || "—", controls(row.scope),
          ])),
        ),
        h("section", { class: "card" }, h("h2", null, "出境"),
          h("p", { class: "muted" }, "许可按类型共享；同类型的评委也受此许可约束。本机后端无需出境许可。"),
          table(["类型", "提供方", "主机", "本机/外部", "声明/推断", "许可", "操作"], data.egress.map((row, index) => [
            index < 4 ? row.kind : `llm（评委 ${index - 3}）`, row.provider, row.host || "未知",
            badge(row.external ? "外部" : "本机", row.external ? "hold" : "neutral"), row.declared ? "已声明" : "推断",
            badge(!row.external ? "无需" : row.granted ? "已授权" : "未授权", row.granted ? "go" : "neutral"),
            row.external ? controls(`egress:${row.kind}`) : "—",
          ])),
        ),
        h("section", { class: "card" }, h("h2", null, "生物特征"),
          h("p", null, data.biometric.reason),
          h("div", { class: "btn-row" },
            h("button", { type: "button", class: "btn", disabled: true }, "本人声音复刻：禁止"),
            h("button", { type: "button", class: "btn", disabled: true }, "照片驱动形象：禁止"),
          ),
        ),
      );
    } catch (err) {
      if (scope.alive) content.replaceChildren(errorBox(err, { retry: load }));
    }
  }

  await load();
}
