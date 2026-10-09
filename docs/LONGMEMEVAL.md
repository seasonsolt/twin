# LongMemEval 评测

`twin eval-longmemeval` 默认使用 `--system twin`，在隔离评测库中执行真实的
导入、档案构建、索引与 PersonaChat 作答链路。旧的 **role-aware raw-history retrieval baseline**
通过 `--system retrieval` 显式选择，作为对照保留；两种系统的成绩不能混用。
现有 `twin eval` 的个人题库、契约和报告保持独立。

## 输入与边界

使用官方 [LongMemEval S cleaned JSON](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/blob/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json)。
数据卡许可为 MIT；固定 HF revision 为 `98d7416c24c778c2fee6e6f3006e7a073259d48f`。
该 S 文件为 277383467 字节、500 题，SHA-256 为
`d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`。
下载数据应放在仓库外的独立空目录。输入是非空 JSON 数组，每题需要：

- `question_id`：全局唯一非空字符串。
- `question_type`：`single-session-user`、`single-session-assistant`、`single-session-preference`、
  `multi-session`、`knowledge-update` 或 `temporal-reasoning`。
- `question`、`question_date`：非空问题和官方格式 `%Y/%m/%d (%a) %H:%M` 的日期，
  如 `2024/01/05 (Fri) 10:00`。
- `answer`：非空字符串或有限数值，保留原生 JSON 数值类型，布尔值不接受。
- `haystack_session_ids`、`haystack_dates`、`haystack_sessions`：非空、长度一致的列表；
  原生会话 ID 可以重复，使用数组下标作为唯一内部会话身份，日期格式同上。
  每个会话至少有一条 `user` / `assistant` 消息；消息内容必须是字符串，允许空白。
- `answer_session_ids`：唯一的证据会话 ID 列表，必须属于历史会话，允许空列表。

加载器只保留规定字段，丢弃消息上的 `has_answer` 和所有未知元数据。
标准答案与证据会话 ID 存在单独的 Gold 对象中；检索和作答只收到 QuestionInput。
问题类型、标准答案、证据标签、题目 ID 都不进入作答提示。
两个角色均保留为原始历史：`user` 映射到评测目标身份，`assistant` 是非 target，
不会成为本人身份、声音样本或本人陈述。默认 twin 使用生产的 `target_only=True` 提取、索引与检索，
因此保留 assistant 历史不等于能召回 assistant-only 证据；尤其应单独阅读 `single-session-assistant` 的结果。
旧 retrieval 对照则可以直接检索两个角色的原始消息。
日期原样保留，不执行时区转换。所有官方提供的历史均参与输入，即使日期晚于 `question_date`；
问题日期只作为普通问题上下文，不触发生产 `as_of` 日期过滤。
真实 S 中有 1475 个这样的会话、13 题包含重复会话 ID、12 条空白消息。
全空白历史走生产无证据答复或弃权，不导入空源；自然弃权不等于后端失败。

## 用法

```sh
# 只验证输入、选择题目和生成私有运行记录；不构造或调用任何后端。
uv run twin eval-longmemeval \
  --dataset /private/tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --out /private/tmp/longmemeval-runs/check-01 --dry-run

# 默认 system=twin，只选 3 题；建档和预测仍会调用模型，不启用评分。
uv run twin --config twin.toml eval-longmemeval \
  --dataset /private/tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --out /private/tmp/longmemeval-runs/predict-01 --limit 3 --offset 0 --no-score

# 显式启用配置评委；使用另一个全新的输出目录。
uv run twin --config twin.toml eval-longmemeval \
  --dataset /private/tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --out /private/tmp/longmemeval-runs/scored-01 --limit 3 --score
```

`--limit` 默认 3 且必须大于零，`--offset` 默认 0 且必须非负；没有选中题目会报错。

正式测试集：LongMemEval S 的 6 种题型各随机抽 5 题，共 30 题，种子 `longmemeval-v1`，用 `--per-type 5 --score` 运行。
每种题型用 `random.Random(f"{seed}:{题型}")` 独立抽样，同样的数据和种子总是选中同样的题目，选中题目按源顺序运行；
`per_type` 与种子计入配置指纹。成绩按题型分别报告，并保留"评委为主模型、不是官方 GPT-4o 评委"的边界。
输出路径先于输入和后端验证，必须位于所有 git 仓库之外，包括符号链接解析后的路径。
运行文件存在时拒绝覆盖；请每次使用新的输出目录。目录权限为 0700，文件为 0600。

追加 `--system retrieval` 可运行旧检索对照；省略 `--system` 等同于 `--system twin`。

三个公开基准的 CLI 都使用 `[llm]` 建档和作答；LongMemEval 的 `--score` 也使用 `[llm]` 作评委。
在 y15 现有配置下，这对应 xjjk 的 `gpt-5.6-sol`，密钥继续由现有 env 的 `TWIN_LLM_KEY` 提供。
CLI 在内存中覆盖评测用的 `chat_llm` 和评委列表，不修改配置文件，避免调用生产环境的 DeepSeek。
检索仍使用 `[embed]`；无评分时不构造评委。直接调用 Python runner 的 twin 模式也使用
调用方的 `settings.llm` 建档和作答，在隔离 Settings 中覆盖 `chat_llm`；仅 retrieval 模式保留
`settings.effective_chat_llm` 行为。
dry-run 不需要配置文件或凭证，也不会创建配置；实际运行需要已配置的作答后端。
实际运行存在预测失败、评委失败或缺失题目时，在保存报告后退出码为 1；dry-run 不受缺失计数影响。
调用采用现有用量记录和 `[pricing]`、`[budget].max_cost_usd`；预算停止后剩余题目记为缺失。
未配置价格的模型费用无法纳入预算，供应商未报告的用量也会标为未知；这不是供应商账单硬限额。

## 默认 twin 链路、隔离与成本

每个 session 经生产 chat parser 解析后，依次使用 `PersonaStore.put_source`、`build_profile`、
`index_persona` 和 `PersonaChat.reply(..., persist=False)`。答案直接取 `ChatReply.reply`；
问题及输出要求放在普通 user 消息中，不另建作答模型或另一套人格、检索、提示引擎。
保留生产回复的弃权、置信度、引用和检索 ID，回答不写回评测历史。
评测显式允许 assistant-only 来源，但不伪造 target 消息，也不修改生产 parser 的默认校验。

解析前复制 Settings，替换数据库路径、测试身份及 aliases；全新私有评测库不会复制、读取或回退到生产库。
运行结束或异常时关闭连接并清理临时库。运行内仅复用同一主体、完全相同合法输入与身份映射、
构建和 embedding 配置的准备结果；不按题目或上下文 ID 单独命中档案，也不跨运行隐式复用。
连接关闭后，缓存仍保留本次运行的私有库以便重开；准备失败状态也被保留，避免重复付费建档。

建档可能对长历史发起多次模型调用，随后还有索引、作答和可选评分的用量。
共享建档成本只计一次，分别记录准备、索引、回答、评分的耗时与用量。
运行元数据包含 `preparation_key`、`cache_hit`、以秒为单位的 `stages` 和准备失败信息；
用量阶段为 `persona.preparation`、`persona.index`、`persona.answer`，评委使用 `longmemeval.judge` 阶段。
必须检查 `BuildReport.failures`；部分建档失败属于准备失败，不能用残缺档案继续并报告成功。
准备及索引错误属于准备失败，阶段记录用于定位；回答和评委失败另行记录。
旧的单次预测金额或“一题一次调用”估算不包含这些建档成本，
不能作为新流程预算。新流程已通过虚构样本的离线生产链路验证，并于 2026-10-09 完成真实三题验证；
结果、包含建档的实际调用量和分析边界见 [验证与失误分析](BENCHMARK_VALIDATION.md)。
小样本不代表全量准确率；因价格未配置，实际费用仍未知。
`--dry-run` 仅验证输入和规划主体，不构造后端、不建档，调用数为零。

## 旧 retrieval 对照的检索与限制

以下参数仅描述 `--system retrieval`，不能用于解释默认 twin 的生产索引或检索。
每条非空白消息按最多 1500 字符分片，保留日期、原生会话 ID、源数组下标、角色、消息和片段序号。
长消息全部分片，不截掉消息前缀以外的内容；最终提示仅包含检索选中的片段。
使用现有 embeddings 与 BM25，按现有 RRF(60) 融合排名。
最终最多选择 12 个片段，片段 JSON 合计不超过 12000 字符，另加问题与少量提示包装。
不把完整历史作为最终提示；对短历史，所有片段也可能恰好落在上限以内。

每题独立建立内存索引，不写生产数据库、不构建或更新档案。
仍需为该题全部历史分片计算 embedding，因此小题数不等于低 embedding 成本。
默认 hashing embedder 可离线工作，但不能作为强语义检索效果的依据。
没有邻接消息扩展、摘要记忆、跨题缓存、专门的时间范围检索或证据召回指标；
分片边界与检索遗漏可能影响更新、时间推理和多会话题目。
真实 S 每题历史约 489k 字符，首三题约 485k / 484k / 502k；全历史 embedding 的费用仍需评估。

## 输出与评分解释

- `hypotheses.jsonl`：每行严格只有 `question_id` 和 `hypothesis`，成功预测后立即写入并刷新。
  失败预测没有虚构回答行。
- `records.jsonl`：逐题状态、预测与评委布尔判断，以及所选系统的检索引用和阶段失败信息；
  retrieval 的有界检索清单至多 12 项，包含源位置、日期、排名、RRF 分数和字符数。
  失败仅保留经过脱敏的错误说明。
- `report.json`：`system`、`system_label`、`protocol_version`、对应检索参数、评分类型、局部评委标识、总计和分类指标。
  CLI 记录输入文件 SHA-256 与配置指纹；后端构造成功后补充现有 `configuration_fingerprint`
  计算的运行配置指纹。仅存摘要，不存绝对路径、配置端点或密钥；dry-run 使用配置摘要，不构造后端。
- `calls.jsonl`、`usage.json`：现有后端调用与用量记录，每题后更新；不记录提示或历史正文，模型及自定义后端身份用哈希表示。

所有输出都应视为私有材料；预测回答可能包含历史事实。终端只输出计数，不输出历史或后端异常详情。
`selected` 是选中题数，`completed` 是成功预测数，`prediction_failures` 是预测失败数，
`missing` 是 dry-run 或预算停止后未执行的题数。`pending` 是仍待执行的题数，最终为 0。
`judge_failures` 是至少一个评委失败的题数，`judge_failed_calls` 是失败评委单元数。
只有所有评委均成功的题目才有分数，分数是各评委布尔判断的均值。
`scored` / `unscored` 明确展示评分覆盖率。

启用评分时，`accuracy_selected` 使用全部已处理题目作为分母，缺失、预测失败和评委失败贡献 0；
最终分母为所有选中题目。这是保守的运行指标，不应把失败等同于已知答案错误。
`accuracy_scored` 仅描述成功完成全评委评分的题目，应结合覆盖率阅读。
无评分或 dry-run 时准确率为 null。`categories` 始终包含六种原始题型，弃权题仍计入各自题型和总计；
另有 `abstention` 子集指标。与官方评分器一致，题目 ID 中包含 `_abs` 即属于弃权题，不要求位于后缀。
运行中报告显示全部 `selected` 和 `pending`；准确率与分类计数反映已经处理的题目。

评分是 **custom/configured judge**，不是官方固定 GPT-4o 等价结果。
规则根据[官方评分代码](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/evaluate_qa.py)
改写（固定 repo revision `9e0b455f4ef0e2ab8f2e582289761153549043fc`，2026-05-11）：
事实与多会话题要求完整或等价答案；时间间隔允许一个单位的偏差；
更新题允许同时提到旧信息；偏好题关注个人信息的正确利用；弃权题要求识别信息不足。
评委返回严格 JSON 布尔值 `correct`，不通过字符串包含 yes 来推断成功。

`hypotheses.jsonl` 的格式可交给[官方评分器](https://github.com/xiaowu0162/LongMemEval#-testing-your-system)。
twin 只导出结果，不下载或执行外部评分脚本。若另行使用官方评分器，应先审阅代码并隔离运行。
官方评分只遍历导出的预测，失败题的缺失会影响分母；必须同时报告本运行的选中数和失败数。
仓库测试全部使用虚构历史；真实小样本运行和效果验证需要另外完成。


## 其他基准

[PersonaMem](PERSONAMEM.md) 和 [Twin-2K-500](TWIN2K500.md) 使用独立适配器与报告。
PersonaMem 按共享上下文截止索引切片；Twin-2K-500 使用 wave 1–3 资料预测保留的 wave 4 题目。
三者默认使用共享的真实 twin 链路，旧检索基线需显式指定 `--system retrieval`。
此前三题小样本及其费用属于旧 retrieval 对照，不能代表新流程的效果或包含建档的总费用。
