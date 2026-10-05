import { h } from "./dom.js";

const JOB_ID_PATTERN = /\bj_[0-9A-Za-z_]+/;

class ApiError extends Error {
  constructor(status, detail, body) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }

  get jobId() {
    const body = this.body;
    if (body && typeof body === "object") {
      if (typeof body.job_id === "string") return body.job_id;
      if (body.detail && typeof body.detail === "object" && typeof body.detail.job_id === "string") {
        return body.detail.job_id;
      }
    }
    const match = JOB_ID_PATTERN.exec(this.detail || "");
    return match ? match[0] : null;
  }
}

function detailOf(body) {
  if (body === null || body === undefined) return "";
  if (typeof body === "string") return body.trim().slice(0, 500);
  const detail = body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (!entry || typeof entry !== "object") return String(entry);
        const where = Array.isArray(entry.loc) ? entry.loc.filter((part) => part !== "body").join(".") : "";
        return where ? `${where}：${entry.msg}` : String(entry.msg ?? "");
      })
      .join("；");
  }
  if (detail && typeof detail === "object") {
    return String(detail.message ?? detail.detail ?? detail.error ?? "");
  }
  return typeof body.message === "string" ? body.message : "";
}

export async function api(path, { method = "GET", json, form, query } = {}) {
  let url = path;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
    }
    const text = params.toString();
    if (text) url += `?${text}`;
  }
  const headers = { Accept: "application/json" };
  const init = { method, headers, credentials: "same-origin", cache: "no-store" };
  if (method !== "GET" && method !== "HEAD") headers["X-Twin"] = "1";
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (form) {
    init.body = form;
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(0, "", null);
  }
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) throw new ApiError(response.status, detailOf(body), body);
  return body;
}

export function describeError(err) {
  if (!(err instanceof ApiError)) {
    return {
      title: "页面出错",
      detail: err instanceof Error ? err.message : String(err),
      hint: "请刷新页面后重试；如果问题持续出现，请查看运行 twin ui 的终端输出。",
    };
  }
  const detail = err.detail;
  switch (err.status) {
    case 0:
      return {
        title: "无法连接本地服务",
        detail: "",
        hint: "确认运行 twin ui 的终端窗口仍在运行（没有被关闭或按了 Ctrl-C），然后刷新页面。",
      };
    case 400:
      return { title: "填写的内容有误", detail, hint: "按上面的提示修改后再试一次。" };
    case 403:
      return {
        title: "请求被安全检查拒绝",
        detail,
        hint: "请用 twin ui 打印的本机地址（127.0.0.1 或 localhost）打开本页面，刷新后重试。",
      };
    case 404:
      return {
        title: "没有找到对应的内容",
        detail,
        hint: "数据可能已被重建或删除。请返回列表刷新后再打开。",
      };
    case 409:
      return {
        title: "当前状态无法执行此操作",
        detail,
        hint: "请按上面的提示处理；如有任务正在运行，请等它完成后再提交。",
      };
    case 413:
      return {
        title: "提交的内容太大",
        detail,
        hint: "上传转写文件时请拆分后分批上传；提交汇报材料或审核内容时请删减后再提交。",
      };
    case 429:
      return {
        title: "排队的任务太多",
        detail,
        hint: "请等前面的聊天任务完成后再提交。",
      };
    case 422:
      return { title: "请求格式不正确", detail, hint: "检查日期（YYYY-MM-DD）和数字是否填写正确。" };
    case 503:
      return {
        title: "模型后端不可用",
        detail,
        hint: "按提示修改 twin.toml 的 [llm] / [embed] 配置或设置密钥所在的环境变量，然后重启 twin ui。浏览认知档案、决策台账和会议原文不受影响。",
      };
    default:
      return {
        title: err.status >= 500 ? "本地服务内部出错" : `请求失败（${err.status}）`,
        detail,
        hint: "查看运行 twin ui 的终端输出了解原因，修正后重试。",
      };
  }
}

export function errorBox(err, { retry, title } = {}) {
  const info = describeError(err);
  return h(
    "div",
    { class: "callout tone-stop", role: "alert" },
    h("p", { class: "callout-title" }, title || info.title),
    info.detail ? h("p", { class: "callout-detail" }, info.detail) : null,
    h("p", { class: "callout-hint" }, info.hint),
    retry ? h("button", { type: "button", class: "btn", onclick: retry }, "重试") : null,
  );
}
