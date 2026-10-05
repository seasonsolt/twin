// General digital twin pages: chat, profile with completeness, and sources with build.
import { api, describeError, errorBox } from "./api.js";
import { badge, empty, field, h, loading, pageHeader, pct, sessionGet, sessionSet, setChildren, toast } from "./dom.js";
import { JobView } from "./jobs.js";
import { REVIEW_LABELS, REVIEW_TONES } from "./labels.js";
import { playbackAction } from "./playback.js";
import { targetName } from "./state.js";

const KIND_OPTIONS = [
  ["questionnaire", "问卷", "建档问卷导出的文字（每题“回答：”下面是答案）"],
  ["meeting", "转录文本", "有说话人的 TXT / Markdown / SRT / VTT / JSON；文件名含日期"],
  ["chat", "聊天记录", "每行“时间 发言人：内容”，或微信式分块，或 CSV / JSON"],
  ["interview", "访谈", "每行“说话人：内容”的访谈稿，日期写在文件名里"],
  ["document", "文档与邮件", "本人写的方案、周报、邮件，按段落导入"],
  ["biography", "传记与他人记述", "别人写的关于本人的传记、年谱、报道；标题里的年份作为下面段落的日期"],
];
const LEVEL_TONES = { 0: "neutral", 1: "info", 2: "go", 3: "accent" };
const CHAT_KEY = "persona.chat";
const POLL_MS = 1000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForJob(jobId, scope) {
  for (;;) {
    await sleep(POLL_MS);
    if (!scope.alive) return null;
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (job.status === "done") return job.result;
    if (job.status === "failed") throw new Error(job.error || "任务失败");
  }
}

// ---------------------------------------------------------------- chat

function loadHistory() {
  const saved = sessionGet(CHAT_KEY);
  return Array.isArray(saved) ? saved : [];
}

function citationList(reply) {
  const cited = Array.isArray(reply.cited) ? reply.cited : [];
  if (!cited.length) return null;
  return h(
    "details",
    { class: "chat-sources" },
    h("summary", null, `依据 ${cited.length} 条`),
    h(
      "ul",
      { class: "plain-list" },
      cited.map((c) =>
        h(
          "li",
          null,
          c.kind === "item"
            ? [badge(c.facet || "档案", "info"), " ", c.text]
            : [badge([c.date, c.channel].filter(Boolean).join(" · ") || "原话", "neutral"), " 「", c.text, "」"],
        ),
      ),
    ),
  );
}

function bubble(turn) {
  if (turn.role === "user") return h("div", { class: "chat-msg chat-user" }, h("p", null, turn.content));
  const reply = turn.reply || {};
  return h(
    "div",
    { class: "chat-msg chat-twin" },
    h("p", null, turn.content),
    h(
      "p",
      { class: "chat-meta" },
      badge(`置信度 ${pct(reply.confidence ?? 0, 0)}`, reply.abstain ? "hold" : "neutral"),
      reply.abstain ? [" ", badge("需要本人确认", "hold"), " ", h("span", { class: "muted" }, reply.abstain_reason || "")] : null,
    ),
    citationList(reply),
    turn.reply ? playbackAction(reply, targetName()) : null,
  );
}

export async function personaChatPage(ctx) {
  const { root, scope } = ctx;
  const name = targetName() || "本人";
  let history = loadHistory();
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const input = h("textarea", { rows: 3, placeholder: `和${name}的分身聊点什么…`, maxlength: 4000 });
  const asOf = h("input", { type: "date" });
  const send = h("button", { type: "submit", class: "btn" }, "发送");
  const clear = h("button", { type: "button", class: "btn secondary" }, "清空对话");
  const errorArea = h("div");

  const render = () => {
    setChildren(log, history.length ? history.map(bubble) : empty("还没有对话", "在下面输入一句话开始。分身只依据已构建的人格档案作答。"));
    log.scrollTop = log.scrollHeight;
  };

  const submit = async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    setChildren(errorArea);
    history = [...history, { role: "user", content: text }];
    input.value = "";
    render();
    send.disabled = true;
    send.textContent = "思考中…";
    try {
      const messages = history.map((t) => ({ role: t.role, content: t.content }));
      const { job_id: jobId } = await api("/api/persona/chat", { method: "POST", json: { messages, as_of: asOf.value || null } });
      const reply = await waitForJob(jobId, scope);
      if (!reply) return;
      history = [...history, { role: "twin", content: reply.reply, reply }];
      sessionSet(CHAT_KEY, history);
      render();
    } catch (err) {
      if (!scope.alive) return;
      history = history.slice(0, -1);
      input.value = text;
      render();
      setChildren(errorArea, errorBox(err, { title: "分身没能回复" }));
    } finally {
      if (scope.alive) {
        send.disabled = false;
        send.textContent = "发送";
      }
    }
  };

  clear.addEventListener("click", () => {
    history = [];
    sessionSet(CHAT_KEY, null);
    render();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(event);
  });

  root.replaceChildren(
    pageHeader(`和${name}的分身聊天`, "分身以本人身份、第一人称作答，只依据人格档案和本人原话；没有依据时会直说并标注“需要本人确认”。回复是模拟，不代表本人意见。"),
    log,
    h(
      "form",
      { class: "card form chat-form", onsubmit: submit },
      field({ label: "你说", input, id: "chat-input", help: "Ctrl / ⌘ + Enter 发送" }),
      h(
        "div",
        { class: "form-row" },
        field({ label: "只用这一天及以前的资料（可选）", input: asOf, id: "chat-asof" }),
        h("div", { class: "btn-row" }, send, clear),
      ),
    ),
    errorArea,
  );
  render();
  ctx.focused = true;
  input.focus();
}

// ---------------------------------------------------------------- profile and completeness

function dimensionTable(report) {
  return h(
    "table",
    { class: "table" },
    h("thead", null, h("tr", null, ["维度", "已授权细项", "覆盖率", "充分率", "验证率", "矛盾"].map((t) => h("th", null, t)))),
    h(
      "tbody",
      null,
      report.dimensions.map((d) =>
        h(
          "tr",
          null,
          h("td", null, `${d.dimension_id} ${d.name}`),
          h("td", null, `${d.consented}/${d.facets}`),
          h("td", null, d.covered == null ? "—" : pct(d.covered, 0)),
          h("td", null, d.sufficient == null ? "—" : pct(d.sufficient, 0)),
          h("td", null, d.verified == null ? "—" : pct(d.verified, 0)),
          h("td", null, String(d.conflicts)),
        ),
      ),
    ),
  );
}

function facetTable(report) {
  const kinds = Object.keys(report.kind_labels);
  return h(
    "table",
    { class: "table" },
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        ["细项", "等级", "充分度", "已确认", "被问 / 答不上"].map((t) => h("th", null, t)),
        kinds.map((k) => h("th", null, report.kind_labels[k])),
      ),
    ),
    h(
      "tbody",
      null,
      report.facets.map((f) =>
        h(
          "tr",
          null,
          h("td", null, `${f.facet_id} ${f.name}`, f.conflicts ? [" ", badge("矛盾", "hold")] : null),
          h("td", null, f.consented ? badge(report.level_labels[f.level], LEVEL_TONES[f.level]) : badge("未授权", "neutral")),
          h("td", null, f.sufficiency.toFixed(2)),
          h("td", null, f.confirmed ? String(f.confirmed) : ""),
          h("td", null, f.asked ? `${f.asked} / ${f.abstained}` : ""),
          kinds.map((k) => h("td", null, f.by_kind[k] ? String(f.by_kind[k]) : "")),
        ),
      ),
    ),
  );
}

function suggestionList(report) {
  if (!report.suggestions.length) return h("p", null, "所有已授权细项都已验证。");
  return h(
    "ul",
    { class: "plain-list" },
    report.suggestions.slice(0, 15).map((s) =>
      h(
        "li",
        null,
        h("strong", null, `${s.facet_id} ${s.name}`),
        `：${s.reason}`,
        s.sources.length ? `；建议来源：${s.sources.map((k) => report.kind_labels[k]).join("、")}` : "",
      ),
    ),
  );
}

function reviewControls(item, onChange) {
  const box = h("div", { class: "btn-row review-actions" });
  const send = async (status, statement) => {
    try {
      const updated = await api(`/api/persona/items/${encodeURIComponent(item.item_id)}/review`, {
        method: "POST",
        json: { status, statement: statement ?? null, note: "" },
      });
      onChange(updated);
    } catch (err) {
      toast(describeError(err).title, "stop");
    }
  };
  const button = (label, handler, cls = "btn small secondary") => {
    const b = h("button", { type: "button", class: cls }, label);
    b.addEventListener("click", handler);
    return b;
  };
  const edit = () => {
    const area = h("textarea", { rows: 3, maxlength: 1000 });
    area.value = item.statement;
    setChildren(
      box,
      area,
      button("保存修改", () => (area.value.trim() ? send("edited", area.value.trim()) : toast("表述不能为空", "hold")), "btn small"),
      button("取消", () => setChildren(box, ...actions())),
    );
    area.focus();
  };
  const actions = () =>
    item.review === "unreviewed"
      ? [button("确认", () => send("confirmed"), "btn small"), button("修改", edit), button("否决", () => send("rejected"))]
      : [button("撤销审核", () => send("unreviewed")), item.review !== "rejected" ? button("修改", edit) : null];
  setChildren(box, ...actions());
  return box;
}

function itemRow(item, onReviewed) {
  const row = h("li", { class: "item-row" });
  const render = (current) => {
    setChildren(
      row,
      h(
        "p",
        { class: "item-statement" },
        badge(REVIEW_LABELS[current.review] || current.review, REVIEW_TONES[current.review] || "neutral"),
        " ",
        badge(current.facet_name, "info"),
        " ",
        current.statement,
      ),
      current.extracted_statement ? h("p", { class: "muted small" }, `原提炼：${current.extracted_statement}`) : null,
      current.applies_when ? h("p", { class: "muted small" }, `适用：${current.applies_when}`) : null,
      current.conflict ? h("p", { class: "callout tone-hold" }, `矛盾：${current.conflict}`) : null,
      h("p", { class: "item-meta muted small" }, `${current.occasions} 处证据`),
      h("blockquote", { class: "small-quote" }, current.evidence[current.evidence.length - 1]?.quote || ""),
      reviewControls(current, (updated) => {
        Object.assign(item, updated);
        render(item);
        onReviewed?.();
      }),
    );
  };
  render(item);
  return row;
}

function itemList(items, onReviewed) {
  if (!items.length) return empty("没有符合条件的条目", "先到“建档问卷”答题，或到“资料与构建”页导入资料并构建。", { href: "#/questionnaire", text: "去答问卷" });
  const groups = new Map();
  for (const item of items) {
    const key = `${item.dimension_id} ${item.dimension_name}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].map(([title, rows]) =>
    h(
      "section",
      { class: "detail-section" },
      h("h3", null, title),
      h("ul", { class: "item-list" }, rows.map((row) => itemRow(row, onReviewed))),
    ),
  );
}

const REVIEW_FILTERS = [
  ["unreviewed", "待核实"],
  ["verified", "已确认"],
  ["all", "全部"],
  ["rejected", "已否决"],
];

function itemsCard(items) {
  let filter = items.some((i) => i.review === "unreviewed") ? "unreviewed" : "all";
  const listArea = h("div");
  const bar = h("div", { class: "btn-row", role: "group", "aria-label": "按核实状态筛选" });
  const matches = (i) =>
    filter === "all"
      ? i.review !== "rejected"
      : filter === "verified"
        ? i.review === "confirmed" || i.review === "edited"
        : i.review === filter;
  const renderBar = () => {
    const count = (f) => items.filter((i) => (f === "all" ? i.review !== "rejected" : f === "verified" ? i.review === "confirmed" || i.review === "edited" : i.review === f)).length;
    setChildren(
      bar,
      REVIEW_FILTERS.map(([key, label]) => {
        const b = h("button", { type: "button", class: ["btn small", key !== filter && "secondary"], "aria-pressed": String(key === filter) }, `${label}（${count(key)}）`);
        b.addEventListener("click", () => {
          filter = key;
          renderBar();
          setChildren(listArea, itemList(items.filter(matches), renderBar));
        });
        return b;
      }),
    );
  };
  renderBar();
  setChildren(listArea, itemList(items.filter(matches), renderBar));
  return h(
    "section",
    { class: "card" },
    h("h2", null, "档案条目"),
    h("p", { class: "muted" }, "AI 提炼的条目默认“未审核”。逐条确认、修改或否决：否决的不再被分身使用，修改后分身用你的表述；只依据未审核条目的回答，置信度最高 60%。"),
    bar,
    listArea,
  );
}

export async function personaProfilePage(ctx) {
  const { root, scope } = ctx;
  root.replaceChildren(pageHeader("人格档案与完成度", "9 个维度、39 个细项。等级：已覆盖＝有证据；充分＝多个场合、多类来源且有实际行为证据；已验证＝测试题实测通过。"), loading());
  const [report, items] = await Promise.all([api("/api/persona/coverage"), api("/api/persona/items", { query: { include_rejected: true } })]);
  if (!scope.alive) return;
  root.replaceChildren(
    pageHeader("人格档案与完成度", `维度体系 ${report.taxonomy}，截至 ${report.as_of}。`),
    h("section", { class: "card" }, h("h2", null, "维度汇总"), dimensionTable(report)),
    h("section", { class: "card" }, h("h2", null, "下一步采集建议"), suggestionList(report)),
    itemsCard(items),
    h("details", { class: "card" }, h("summary", null, "细项 × 来源矩阵"), facetTable(report)),
  );
}

// ---------------------------------------------------------------- sources and build

function sourceTable(sources, reload) {
  if (!sources.length) return empty("还没有导入资料", "从上面选择资料类型和文件导入。");
  return h(
    "table",
    { class: "table" },
    h("thead", null, h("tr", null, ["资料", "类型", "本人 / 全部", "日期", ""].map((t) => h("th", null, t)))),
    h(
      "tbody",
      null,
      sources.map((s) => {
        const remove = h("button", { type: "button", class: "link-btn" }, "删除");
        remove.addEventListener("click", async () => {
          if (!window.confirm(`删除“${s.title}”及从它提炼的档案内容？下次构建时生效。`)) return;
          try {
            await api(`/api/persona/sources/${encodeURIComponent(s.source_id)}`, { method: "DELETE" });
            reload();
          } catch (err) {
            toast(describeError(err).title, "stop");
          }
        });
        return h(
          "tr",
          null,
          h("td", null, s.title, s.declined_facets.length ? h("p", { class: "muted small" }, `未授权细项：${s.declined_facets.join("、")}`) : null),
          h("td", null, badge(s.kind_label, s.evidence_class === "self_report" ? "redirect" : "go")),
          h("td", null, `${s.n_target} / ${s.n_expressions}`),
          h("td", null, [s.first_date, s.last_date].filter(Boolean).join(" 至 ") || "—"),
          h("td", null, remove),
        );
      }),
    ),
  );
}

export async function personaSourcesPage(ctx) {
  const { root, scope } = ctx;
  const kind = h("select", null, KIND_OPTIONS.map(([v, label]) => h("option", { value: v }, label)));
  const kindHelp = h("p", { class: "help" }, KIND_OPTIONS[0][2]);
  kind.addEventListener("change", () => {
    kindHelp.textContent = KIND_OPTIONS.find(([v]) => v === kind.value)?.[2] || "";
  });
  const files = h("input", { type: "file", multiple: true, accept: ".txt,.md,.csv,.json" });
  const date = h("input", { type: "date" });
  const upload = h("button", { type: "submit", class: "btn" }, "导入");
  const importResult = h("div");
  const list = h("div", null, loading());
  const buildButton = h("button", { type: "button", class: "btn" }, "构建人格档案");
  const buildResult = h("div");

  const reload = async () => {
    try {
      const sources = await api("/api/persona/sources");
      if (scope.alive) setChildren(list, sourceTable(sources, reload));
    } catch (err) {
      if (scope.alive) setChildren(list, errorBox(err, { retry: reload }));
    }
  };

  const buildJob = new JobView(scope, {
    kind: "persona_build",
    storageKey: "job.personaBuild",
    title: "人格档案构建进度",
    onBusy: (busy) => {
      buildButton.disabled = busy;
      buildButton.textContent = busy ? "构建中…" : "构建人格档案";
    },
    onDone: (job, { restored }) => {
      const r = job.result || {};
      setChildren(
        buildResult,
        h(
          "p",
          { class: "callout tone-go" },
          `资料 ${r.sources ?? 0} 份，本次抽取 ${r.chunks_extracted ?? 0} 块，候选 ${r.candidates ?? 0} 条，档案条目 ${r.items ?? 0} 条。`,
          r.failures?.length ? ` 有 ${r.failures.length} 处失败，再次构建会自动补跑。` : "",
          " ",
          h("a", { href: "#/persona" }, "查看档案与完成度"),
        ),
      );
      if (!restored) toast("人格档案已更新。", "go");
    },
  });

  const submit = async (event) => {
    event.preventDefault();
    if (!files.files.length) {
      toast("请先选择文件", "hold");
      return;
    }
    const form = new FormData();
    for (const f of files.files) form.append("files", f, f.name);
    upload.disabled = true;
    try {
      const result = await api("/api/persona/import", { method: "POST", form, query: { kind: kind.value, date: date.value } });
      setChildren(
        importResult,
        h(
          "ul",
          { class: "plain-list" },
          result.imported.map((s) => h("li", null, `${s.new ? "已导入" : "已更新"}：${s.title}（本人 ${s.n_target} 条）`)),
          result.skipped.map((s) => h("li", { class: "tone-text-hold" }, `未导入：${s.file}：${s.reason}`)),
        ),
      );
      files.value = "";
      reload();
    } catch (err) {
      setChildren(importResult, errorBox(err, { title: "导入失败" }));
    } finally {
      upload.disabled = false;
    }
  };

  buildButton.addEventListener("click", () => buildJob.start("/api/persona/build", {}));

  root.replaceChildren(
    pageHeader("资料与构建", "导入问卷、聊天记录、访谈和文档。问卷和访谈记为“本人自述”，聊天和文档记为“实际行为”，完成度会分开统计。导入后点“构建人格档案”。"),
    h(
      "form",
      { class: "card form", onsubmit: submit },
      h("div", { class: "form-row" }, field({ label: "资料类型", input: kind, id: "src-kind" }), field({ label: "资料日期（可选）", input: date, id: "src-date", help: "问卷、访谈、文档默认从文件名识别日期" })),
      kindHelp,
      field({ label: "文件", input: files, id: "src-files", help: "支持 .txt .md .csv .json，可多选" }),
      h("div", { class: "btn-row" }, upload),
      importResult,
    ),
    h("section", { class: "card" }, h("h2", null, "已导入的资料"), list),
    h("section", { class: "card" }, h("h2", null, "构建"), h("p", { class: "muted" }, "只处理新增或变化的资料；已经完成的模型调用不会重复。"), h("div", { class: "btn-row" }, buildButton), buildResult),
    buildJob.el,
  );
  buildJob.restore();
  await reload();
}

// ---------------------------------------------------------------- questionnaire

const SAVE_DELAY_MS = 1500;

export async function personaQuestionnairePage(ctx) {
  const { root, scope, query } = ctx;
  const round = query.get("round") === "retest" ? "retest" : "initial";
  const title = round === "retest" ? "问卷重测" : "建档问卷";
  root.replaceChildren(pageHeader(title), loading());
  const data = await api("/api/persona/questionnaire", { query: { round } });
  if (!scope.alive) return;
  const questions = data.questions;
  const answers = { ...data.answers };
  let index = Math.max(0, questions.findIndex((q) => !answers[q.id]));
  if (index >= questions.length) index = 0;
  let saveTimer = null;
  let dirty = false;

  const saveState = h("span", { class: "muted small" }, data.updated_at ? `草稿已保存（${data.updated_at.slice(5, 16).replace("T", " ")}）` : "");
  const progress = h("p", { class: "muted" });
  const grid = h("div", { class: "q-grid", role: "navigation", "aria-label": "题目总览" });
  const card = h("section", { class: "card q-card" });
  const submitArea = h("div");
  const buildJob = new JobView(scope, {
    kind: "persona_build",
    storageKey: "job.personaBuild",
    title: "人格档案构建进度",
    onDone: (_job, { restored }) => {
      if (!restored) toast("人格档案已根据问卷更新。", "go");
      setChildren(submitArea, h("p", { class: "callout tone-go" }, "构建完成。", " ", h("a", { href: "#/persona" }, "查看人格档案与完成度"), "，或者 ", h("a", { href: "#/chat" }, "去和分身聊天"), "。"));
    },
  });

  const answeredCount = () => questions.filter((q) => (answers[q.id] || "").trim()).length;

  const save = async () => {
    clearTimeout(saveTimer);
    if (!dirty) return;
    dirty = false;
    saveState.textContent = "正在保存…";
    try {
      const result = await api("/api/persona/questionnaire/draft", { method: "PUT", json: { round, answers } });
      if (scope.alive) saveState.textContent = `草稿已保存（${(result.updated_at || "").slice(11, 16)}）`;
    } catch (err) {
      dirty = true;
      if (scope.alive) saveState.textContent = `保存失败：${describeError(err).title}，稍后会重试`;
    }
  };
  scope.onDispose(() => save());

  const renderGrid = () => {
    progress.textContent = `已答 ${answeredCount()} / ${questions.length} 题`;
    setChildren(
      grid,
      questions.map((q, i) => {
        const done = Boolean((answers[q.id] || "").trim());
        const btn = h(
          "button",
          { type: "button", class: ["q-dot", done && "q-done", i === index && "q-current", q.test && "q-test"], title: `第 ${q.number} 题${q.test ? "（测试题）" : ""}${done ? "，已答" : ""}`, "aria-current": i === index ? "step" : null },
          String(q.number),
        );
        btn.addEventListener("click", () => go(i));
        return btn;
      }),
    );
  };

  const renderCard = () => {
    const q = questions[index];
    const input = h("textarea", { rows: 9, maxlength: 4000, placeholder: q.kind === "情境" ? "写你当时真正会说出口的原话" : "尽量举真实的例子" });
    input.value = answers[q.id] || "";
    input.addEventListener("input", () => {
      answers[q.id] = input.value;
      dirty = true;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, SAVE_DELAY_MS);
      renderGrid();
    });
    const prev = h("button", { type: "button", class: "btn secondary", disabled: index === 0 }, "上一题");
    const next = h("button", { type: "button", class: "btn" }, index === questions.length - 1 ? "到最后了" : "下一题");
    next.disabled = index === questions.length - 1;
    prev.addEventListener("click", () => go(index - 1));
    next.addEventListener("click", () => go(index + 1));
    setChildren(
      card,
      h("p", { class: "muted small" }, q.section),
      h(
        "h2",
        { class: "q-title" },
        `${q.number}. `,
        q.text,
      ),
      h(
        "p",
        { class: "badges" },
        badge(q.kind, "neutral"),
        q.test ? badge("测试题：不进档案，只用来检验分身", "hold") : null,
        q.optional ? badge("可跳过：不填即不授权采集这一项", "redirect") : null,
        h("span", { class: "muted small" }, ` 对应细项：${q.facets.join("、")}`),
      ),
      field({ label: "回答", input, id: "q-answer" }),
      h("div", { class: "btn-row" }, prev, next, saveState),
    );
    input.focus();
  };

  const go = (i) => {
    if (i < 0 || i >= questions.length) return;
    save();
    index = i;
    renderGrid();
    renderCard();
  };

  const submit = async () => {
    await save();
    const done = answeredCount();
    const left = questions.length - done;
    const note = round === "initial" && data.status === "submitted" ? "会替换上次提交的答案，并重新构建档案。" : "";
    if (!window.confirm(`已答 ${done} 题${left ? `，还有 ${left} 题没答` : ""}。确定提交？${note}`)) return;
    try {
      const result = await api("/api/persona/questionnaire/submit", { method: "POST", json: { round, answers } });
      if (!scope.alive) return;
      setChildren(submitArea, h("p", { class: "callout tone-go" }, result.notice));
      if (result.job_id) buildJob.attach(result.job_id);
      toast(result.notice, "go");
    } catch (err) {
      setChildren(submitArea, errorBox(err, { title: "提交失败" }));
    }
  };

  const submitButton = h("button", { type: "button", class: "btn" }, round === "retest" ? "提交重测" : "交卷并构建档案");
  submitButton.addEventListener("click", submit);
  const lead =
    round === "retest"
      ? `再答一次 ${questions.length} 道测试题，不要翻看上次的答案。用来算你自己前后的一致程度。${data.retest_from ? `建议 ${data.retest_from} 之后再做。` : ""}`
      : "一题一屏，回答自动保存成草稿，可以分几次填完。情境题请写你会说出口的原话。标了“测试题”的不进档案；“可跳过”的不填即不授权。";
  const banner =
    data.status === "submitted"
      ? h("p", { class: "callout tone-info" }, `已于 ${String(data.submitted_at).replace("T", " ").slice(0, 16)} 提交。可以修改后重新提交。`, round === "initial" ? [" ", h("a", { href: "#/questionnaire?round=retest" }, "三周后去做重测")] : null)
      : null;

  setChildren(
    root,
    pageHeader(title, lead),
    banner,
    progress,
    grid,
    card,
    h("section", { class: "card" }, h("div", { class: "btn-row" }, submitButton), submitArea),
    buildJob.el,
  );
  buildJob.restore();
  renderGrid();
  renderCard();
  ctx.focused = true;
}
