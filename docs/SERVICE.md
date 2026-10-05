# 服务 API 与 MCP

让本人的其他工具、Agent 向分身提问。HTTP API 与 stdio MCP 共用 `ServiceAnswer`，
内容只来自 L3 `PersonaChat`：只问一轮，不增加生成、改写或检索路径。
请先导入资料并运行 `twin persona build`（包含索引构建）。没有依据时可能弃权。

## 回答契约

`ServiceAnswer` v1 为冻结、只增不删的契约：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 固定为 `1` |
| `answer` | L3 的回答原文，不改写 |
| `abstain` / `abstain_reason` | 是否弃权及原因 |
| `confidence` | L3 给出的置信度，不提高 |
| `citations` | 已解析的证据引用，保持 L3 顺序 |
| `as_of` | 截止日期（含当天），未指定为 `null` |
| `label` | `AI 合成 · 模拟推演，不代表本人意见` |
| `persona_name` | 配置的本人名字 |
| `generated_at` | 带时区的 UTC 生成时间 |

每条引用含 `ref_id`、`kind`（`item` 或 `expression`）、`quote`、`date`、`source_kind`。
`quote` 使用聊天实际使用的隐私视图：条目取最后一条可见证据，表达取本人可见文本；
沿用聊天的空白整理和长度截断（条目 120 字符、表达 600 字符），不另造引文。
按日期提问时排除未来和无日期的表达/证据；条目只保留当天及以前的证据。

## HTTP API

### 启动

```bash
export TWIN_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
twin api                       # 127.0.0.1:8780
```

令牌必须非空且至少 32 个字符，值只放环境变量，不写入配置、源码或客户端示例。
可在配置中指定变量名和限流阈值：

```toml
[api]
token_env = "TWIN_API_TOKEN"
rate_per_minute = 30
```

`--host`、`--port` 改变监听地址与端口；非 loopback 地址必须显式加 `--allow-remote`。
这不会自动放宽 Host 白名单：默认只接受 `localhost`、`127.0.0.1`、`[::1]`，
其他地址/域名需 `--allow-host 主机名`（可重复），不支持通配符。端口不参与 Host 匹配。
远程访问请使用可信网络和 TLS 反向代理，明文 HTTP 会暴露 Bearer 令牌。

### 接口

| 方法与路径 | 授权 | 返回 |
| --- | --- | --- |
| `GET /v1/health` | 无 | `{"status":"ok"}`，不构造后端 |
| `GET /v1/identity` | Bearer | `name`、预置 `avatar`、预置 `voice`、`label`；无授权/备注 |
| `POST /v1/ask` | Bearer | `ServiceAnswer`；输入 `{"question":"…","as_of":"YYYY-MM-DD"}`，日期可省略或为 `null` |

问题最多 2000 字符；HTTP 请求体最多 16 KiB。所有 HTTP 响应（包括错误）均带
`X-AI-Generated: twin`、`Cache-Control: no-store` 与安全加固响应头。不支持 WebSocket。
身份及提问请求使用 `Authorization: Bearer <令牌>`，通过 `hmac.compare_digest` 比较。
不要求网页接口的 `X-Twin` 请求头。

每个有效令牌共用进程内的 60 秒滑动窗口，默认每分钟最多 30 次；健康检查与无效令牌不占额度，
授权后的无效请求也计数。超限返回 `429` 和秒数形式的 `Retry-After`。
重启会重置窗口；不是跨进程、跨机器的限流。

```bash
curl http://127.0.0.1:8780/v1/health
curl -H "Authorization: Bearer $TWIN_API_TOKEN" http://127.0.0.1:8780/v1/identity
curl -H "Authorization: Bearer $TWIN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"你怎么看远程办公？","as_of":"2025-12-31"}' \
  http://127.0.0.1:8780/v1/ask
```

错误：缺少/错误令牌 `401`；Host 不允许或出境拒绝 `403`；参数错误 `400`；
请求体过大 `413`；限流 `429`；后端错误 `503`（固定中文消息，无后端地址、密钥、问题原文）。
出境拒绝保留中文原因及授权命令，不回显令牌或问题。

## MCP（stdio）

```bash
twin mcp
```

使用官方 Python MCP SDK 的 FastMCP，只通过 stdio 读写协议，不启动 HTTP 或其他网络监听。
HTTP Bearer 令牌不用于 MCP；启动进程的本机权限就是访问边界。
不要把它作为无鉴权的远程 stdio 转发服务。

| 工具 | 参数 | 返回 |
| --- | --- | --- |
| `ask_twin` | `question: str`，可选 `as_of: str | null`（`YYYY-MM-DD`） | `structuredContent` 为 `ServiceAnswer`，并附以显式 AI 标识开头的简短文本 |
| `twin_identity` | 无 | `structuredContent` 为 `name`、`avatar`、`voice`、`label`，并附带标识的文本 |

两个工具均公布输出 schema；错误通过 MCP 工具错误返回（`isError: true`）。
出境拒绝包含中文原因及授权命令；后端异常使用固定中文消息，日期/长度错误不回显输入。

客户端配置示例（替换项目路径；仅展示命令与参数，不展示环境变量值）：

```json
{
  "mcpServers": {
    "twin": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/twin", "twin", "mcp"]
    }
  }
}
```

环境变量**名称**：`TWIN_CONFIG`（可选配置路径）、`TWIN_LLM_KEY`、`TWIN_EMBED_KEY`；
如配置了其他密钥变量名则使用该名称；`OPENAI_BASE_URL` 是可选端点回退。
让客户端继承这些变量，或通过客户端的秘密管理功能提供值。无需 `TWIN_API_TOKEN`。
注意 `uv` 必须在客户端的 PATH 中，配置文件默认从项目目录读取。

## 隐私与治理

- 两个入口都以 `persist=False` 调用聊天，不保存问题、回答或聊天日志。
  不向 stderr 记录问题、回答、令牌或后端异常正文。调用方自行保存的结果不受此规则保护。
- 引用复用 `expression_view` 和聊天条目视图，而非直接读取他人原文；默认化名规则与网页/CLI 一致。
- LLM 与 embed 都在首次懒构造前调用 `require_configured_egress`；外部后端必须有最新的
  `egress:llm` / `egress:embed` 授权。健康检查与身份工具不调用模型。
  本机转发代理需显式声明 `egress = "external"`。
- 后端缓存不热更新授权；撤回后重启 API/MCP 进程。注入的 `chat_factory` 仅是可信离线测试接缝。
- 复用 `usage.py`，按 `service` 阶段记录无提示词的调用行、用量和错误类型，仅保存在进程内；
  使用配置 pricing 与进程累计 budget，不写追踪文件，不把统计加入回答契约。重启清零，未知价格仍无法预算。
- 答案和身份均带统一显式 AI 标识；HTTP 还带隐式响应头。调用方呈现结果时必须保留标识，
  不得当作本人承诺或意见。
