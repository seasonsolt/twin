import { api, describeError } from "./api.js";
import { badge, formatElapsed, h, parseServerTime, sessionGet, sessionSet } from "./dom.js";
import { JOB_KIND_LABELS, JOB_STATUS_LABELS, JOB_STATUS_TONES } from "./labels.js";

const POLL_MS = 1000;
const RETRY_MS = 2000;
const MAX_SILENT_RETRIES = 15;
const STAGE_PATTERN = /^\[(\d+)\/(\d+)\]\s*(.*)/;

const MODEL_HINT = "检查 twin.toml 的 [llm] 配置和密钥所在的环境变量，修正后重启 twin ui 再试。";

const FAILURE_HINTS = {
  persona_build: "已经完成的模型调用都保存在资料库里，修正问题后再次构建会跳过它们。常见原因：模型或向量服务的配置、密钥、网络问题。",
  chat: MODEL_HINT,
};

// Fallback for a server that does not report job.stage: the last "[n/N] label" progress line.
function stageOf(lines) {
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const match = STAGE_PATTERN.exec(lines[i]);
    if (match) return { current: Number(match[1]), total: Number(match[2]), label: match[3].trim() };
  }
  return null;
}

export class JobView {
  constructor(scope, { kind, storageKey, onDone, onBusy, logOpen = false, title = "任务进度" }) {
    this.scope = scope;
    this.kind = kind;
    this.storageKey = storageKey;
    this.onDone = onDone;
    this.onBusy = onBusy;
    this.jobId = null;
    this.restored = false;
    this.sawActive = false;
    this.failures = 0;
    this.firstSeen = 0;
    this.lastStatus = null;
    this.shownStatus = null;

    this.statusSlot = h("span", { class: "job-status" });
    this.kindText = h("span", { class: "job-kind" });
    this.elapsed = h("span", { class: "job-elapsed" });
    this.barFill = h("div", { class: "bar-fill" });
    this.bar = h("div", { class: "bar", role: "progressbar", "aria-label": title }, this.barFill);
    this.stage = h("p", { class: "job-stage" });
    this.latest = h("p", { class: "job-latest" });
    this.milestones = h("ul", { class: "job-milestones" });
    this.log = h("pre", { class: "job-log", tabindex: "0", "aria-label": "详细日志" });
    this.logCount = h("span", null, "详细日志（英文）");
    this.logWrap = h("details", { class: "job-log-wrap", open: logOpen }, h("summary", null, this.logCount), this.log);
    this.notice = h("div", { class: "job-notice" });
    this.message = h("div", { class: "job-message" });
    this.live = h("p", { class: "visually-hidden", "aria-live": "polite" });
    this.el = h(
      "section",
      { class: "job card", hidden: true, "aria-label": title },
      h("div", { class: "job-head" }, this.statusSlot, this.kindText, this.elapsed),
      this.bar,
      this.stage,
      this.latest,
      this.milestones,
      this.notice,
      this.logWrap,
      this.message,
      this.live,
    );
  }

  get busy() {
    return this.lastStatus === "queued" || this.lastStatus === "running" || this.lastStatus === "submitting";
  }

  setBusy(status) {
    this.lastStatus = status;
    if (this.onBusy) this.onBusy(this.busy);
  }

  restore() {
    const saved = this.storageKey ? sessionGet(this.storageKey) : null;
    if (typeof saved === "string" && saved) this.attach(saved, { restored: true });
  }

  reset() {
    this.jobId = null;
    this.failures = 0;
    this.notice.replaceChildren();
    this.message.replaceChildren();
    this.log.textContent = "";
    this.latest.textContent = "";
    this.stage.textContent = "";
    this.milestones.replaceChildren();
    this.logCount.textContent = "详细日志（英文）";
    this.elapsed.textContent = "";
    this.kindText.textContent = "";
    this.statusSlot.replaceChildren();
    this.live.textContent = "";
    this.shownStatus = null;
    this.setBar(null);
    this.showTracking(true);
  }

  showTracking(visible) {
    this.bar.hidden = !visible;
    this.logWrap.hidden = !visible;
  }

  hide() {
    this.reset();
    this.el.hidden = true;
    if (this.storageKey) sessionSet(this.storageKey, null);
    this.setBusy(null);
  }

  async start(path, options) {
    this.reset();
    if (this.storageKey) sessionSet(this.storageKey, null);
    this.el.hidden = false;
    this.statusSlot.replaceChildren(badge("提交中", "neutral"));
    this.latest.textContent = "正在提交任务…";
    this.setBar(null);
    this.setBusy("submitting");
    try {
      const response = await api(path, { method: "POST", ...options });
      if (!this.scope.alive) return;
      if (!response || typeof response.job_id !== "string") throw new Error("服务没有返回任务编号");
      this.attach(response.job_id);
    } catch (err) {
      if (!this.scope.alive) return;
      const running = err && err.status === 409 ? err.jobId : null;
      if (running) {
        this.attach(running);
        this.notice.replaceChildren(
          h(
            "p",
            { class: "callout tone-hold" },
            "已有构建、评测、导入或重建索引任务在运行，同一时间只能运行一个。下面显示正在运行的任务，它结束后可以重新提交。",
          ),
        );
        return;
      }
      this.latest.textContent = "";
      this.showTracking(false);
      this.statusSlot.replaceChildren(badge("未能提交", "stop"));
      this.showError(err);
      this.setBusy(null);
    }
  }

  attach(jobId, { restored = false } = {}) {
    this.jobId = jobId;
    this.restored = restored;
    this.sawActive = false;
    this.failures = 0;
    this.firstSeen = Date.now();
    this.shownStatus = null;
    this.showTracking(true);
    this.el.hidden = false;
    if (this.storageKey) sessionSet(this.storageKey, jobId);
    if (!restored) this.setBusy("queued");
    this.poll(jobId);
  }

  async poll(jobId) {
    if (!this.scope.alive || this.jobId !== jobId) return;
    let job;
    try {
      job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    } catch (err) {
      if (!this.scope.alive || this.jobId !== jobId) return;
      if (err && err.status === 404) {
        if (this.restored) {
          this.hide();
          return;
        }
        this.statusSlot.replaceChildren(badge("已失效", "stop"));
        this.message.replaceChildren(
          h(
            "div",
            { class: "callout tone-stop", role: "alert" },
            h("p", { class: "callout-title" }, "任务记录已不存在"),
            h("p", { class: "callout-hint" }, "本地服务可能已经重启，内存中的任务记录随之清空。请重新发起。"),
          ),
        );
        this.setBusy(null);
        if (this.storageKey) sessionSet(this.storageKey, null);
        return;
      }
      this.failures += 1;
      const info = describeError(err);
      if (this.failures < MAX_SILENT_RETRIES) {
        this.latest.textContent = `${info.title}，正在重试（第 ${this.failures} 次）…`;
        this.scope.timeout(() => this.poll(jobId), RETRY_MS);
        return;
      }
      this.latest.textContent = "";
      this.statusSlot.replaceChildren(badge("连接中断", "stop"));
      this.message.replaceChildren(
        h(
          "div",
          { class: "callout tone-stop", role: "alert" },
          h("p", { class: "callout-title" }, `${info.title}，已停止自动重试`),
          h(
            "p",
            { class: "callout-hint" },
            "本地服务可能已经停止。请在终端重新运行 twin ui（例如 .venv/bin/twin --config twin.toml ui），然后点“重新连接”。服务重启后，之前正在运行的任务会丢失，需要重新提交。",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn",
              onclick: () => {
                this.failures = 0;
                this.message.replaceChildren();
                this.statusSlot.replaceChildren(badge("重新连接中", "hold"));
                this.poll(jobId);
              },
            },
            "重新连接",
          ),
        ),
      );
      this.setBusy(null);
      return;
    }
    if (!this.scope.alive || this.jobId !== jobId) return;
    this.failures = 0;
    this.render(job);
    if (job.status === "done" || job.status === "failed") {
      this.finish(job);
      return;
    }
    this.scope.timeout(() => this.poll(jobId), POLL_MS);
  }

  render(job) {
    const status = job.status in JOB_STATUS_LABELS ? job.status : "running";
    if (status === "queued" || status === "running") this.sawActive = true;
    if (status !== this.shownStatus) {
      this.shownStatus = status;
      this.statusSlot.replaceChildren(badge(JOB_STATUS_LABELS[status], JOB_STATUS_TONES[status]));
      this.live.textContent = `${JOB_KIND_LABELS[job.kind] || "任务"}${JOB_STATUS_LABELS[status]}`;
      this.setBusy(status);
    }
    this.kindText.textContent = JOB_KIND_LABELS[job.kind] || "";

    const start = parseServerTime(job.started) ?? parseServerTime(job.created);
    const end = parseServerTime(job.finished);
    let elapsedMs = start !== null ? (end ?? Date.now()) - start : Date.now() - this.firstSeen;
    if (!Number.isFinite(elapsedMs) || elapsedMs < 0) elapsedMs = Date.now() - this.firstSeen;
    const verb = status === "done" || status === "failed" ? "共用时" : status === "queued" ? "已等待" : "已用时";
    this.elapsed.textContent = `${verb} ${formatElapsed(elapsedMs)}`;

    const lines = Array.isArray(job.progress) ? job.progress.map(String) : [];
    const stage = job.stage && typeof job.stage === "object" ? job.stage : job.stage === undefined ? stageOf(lines) : null;
    const tally = job.tally && typeof job.tally === "object" ? job.tally : null;
    const done = Number(tally?.done) || 0;
    const failed = Number(tally?.failed) || 0;
    const expected = typeof tally?.total === "number" && tally.total > 0 ? tally.total : null;
    if (status === "done") this.setBar(1);
    else if (stage && stage.total > 0) this.setBar((stage.current - 1) / stage.total);
    else if (expected) this.setBar((done + failed) / expected);
    else if (status === "failed") this.setBar(0);
    else this.setBar(null);
    this.bar.classList.toggle("bar-failed", status === "failed");

    const counted =
      done || failed || expected
        ? `已完成 ${done}${expected ? ` / ${expected}` : ""} 项${failed ? `（失败 ${failed}）` : ""}`
        : "";
    if (stage) this.stage.textContent = `第 ${stage.current}/${stage.total} 步：${stage.label}${counted ? `，${counted}` : ""}`;
    else this.stage.textContent = counted ? `进度：${counted}` : "";

    // Milestones are the stage markers and the Chinese summary lines; the English per-call lines stay in the log.
    const milestones = Array.isArray(job.milestones) ? job.milestones.map(String) : [];
    const summaries = milestones.filter((line) => !STAGE_PATTERN.test(line));
    if (stage) {
      this.milestones.replaceChildren(...summaries.map((line) => h("li", null, line)));
      this.latest.textContent = status === "queued" ? "排队等待中…" : "";
    } else {
      this.milestones.replaceChildren();
      if (status === "queued") this.latest.textContent = "排队等待中…";
      else if (status === "running") this.latest.textContent = summaries[summaries.length - 1] || "已开始，正在处理…";
      else this.latest.textContent = "";
    }

    const text = lines.join("\n");
    if (this.log.textContent !== text) {
      const nearBottom = this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 40;
      this.log.textContent = text;
      if (nearBottom) this.log.scrollTop = this.log.scrollHeight;
    }
    this.logCount.textContent = lines.length ? `详细日志（英文，最近 ${lines.length} 行）` : "详细日志（暂无）";
  }

  setBar(ratio) {
    if (ratio === null) {
      this.bar.classList.add("bar-indeterminate");
      this.barFill.style.width = "";
      this.bar.removeAttribute("aria-valuenow");
      this.bar.removeAttribute("aria-valuemin");
      this.bar.removeAttribute("aria-valuemax");
      return;
    }
    const percent = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
    this.bar.classList.remove("bar-indeterminate");
    this.barFill.style.width = `${percent}%`;
    this.bar.setAttribute("aria-valuemin", "0");
    this.bar.setAttribute("aria-valuemax", "100");
    this.bar.setAttribute("aria-valuenow", String(percent));
  }

  finish(job) {
    this.setBusy(null);
    if (job.status === "failed") {
      const hint = FAILURE_HINTS[job.kind] || "查看上面的进度日志了解原因，修正后重试。";
      const title = `${JOB_KIND_LABELS[job.kind] || "任务"}失败`;
      let detail = job.error ? String(job.error) : "";
      if (detail.startsWith(title)) detail = detail.slice(title.length).replace(/^[：:]\s*/, "");
      this.message.replaceChildren(
        h(
          "div",
          { class: "callout tone-stop", role: "alert" },
          h("p", { class: "callout-title" }, title),
          detail ? h("p", { class: "callout-detail" }, detail) : null,
          h("p", { class: "callout-hint" }, hint),
        ),
      );
      return;
    }
    this.message.replaceChildren();
    if (this.kind && job.kind && job.kind !== this.kind) {
      this.notice.replaceChildren(
        h("p", { class: "callout tone-go" }, `正在运行的${JOB_KIND_LABELS[job.kind] || "任务"}已完成，现在可以重新提交。`),
      );
      if (this.storageKey) sessionSet(this.storageKey, null);
      return;
    }
    if (this.onDone) this.onDone(job, { restored: this.restored && !this.sawActive });
  }

  showError(err) {
    const info = describeError(err);
    this.message.replaceChildren(
      h(
        "div",
        { class: "callout tone-stop", role: "alert" },
        h("p", { class: "callout-title" }, info.title),
        info.detail ? h("p", { class: "callout-detail" }, info.detail) : null,
        h("p", { class: "callout-hint" }, info.hint),
      ),
    );
  }
}

export async function findRunningJob(kinds) {
  try {
    const jobs = await api("/api/jobs");
    if (!Array.isArray(jobs)) return null;
    return jobs.find((job) => kinds.includes(job.kind) && (job.status === "running" || job.status === "queued")) || null;
  } catch {
    return null;
  }
}
