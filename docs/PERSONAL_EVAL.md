# 本人资料评测

题库、persona 参考文本及输出必须放在仓库之外；仓库内只保留虚构测试样例。

```sh
twin --config /private/path/twin.toml eval \
  --evalset /private/path/evalset.json \
  --persona-ref /private/path/persona.txt \
  --out /private/path/run-a --repeats 3

twin --config /private/path/twin.toml eval-compare \
  /private/path/run-a/records.json /private/path/run-b/records.json \
  --out /private/path/comparison
```

默认运行全部分类（包含 update）；`--categories fact,unanswerable,style,general` 可排除 update，
也可重复该选项。
输出目录（包含解析符号链接后的路径）位于 git 仓库内时拒绝写入，除非显式
`--allow-in-repo`。输出目录权限 0700，`records.json`、`report.json`、`report.md`
权限 0600；records 经来源记录模块写入并脱敏配置中的端点和环境变量密钥。
文件含个人资料，仍需自行控制备份、分享和模型端点授权。

题库为非空 JSON 列表；id 必须唯一，文本字段非空：

- 每项：id、category、question。
- fact：answer、evidence（文本或文本列表）、source、doc_id（空串时回退 source）。
- update：answer、add_fact、modified_fact、modified_answer。
- unanswerable / style / general：不需要标准答案。

被测分身只收到 id、category、prompt，不收到标准答案、证据、更新字段或 persona
参考文本。每次重复是独立单轮对话；不持久化聊天日志，不编辑真实记忆。评测错误隐藏
后端异常详情，进度及调用追踪不包含题目或回答文本；records 含完整题目及回答。

回答使用可选 `[chat_llm]`，未配置时沿用 `[llm]`，与网页、CLI 聊天和 HTTP/MCP 服务一致。
对同一已构建档案评测不同聊天模型，只需修改 `[chat_llm]` 并使用新的输出目录；
排除 update 时无需重新构建档案。update 的增量提取/构建仍使用 `[llm]`。
`[chat_llm]` 支持与 `[llm]` 相同的字段；两者都支持 `extra_body` 表，原样传入
OpenAI 兼容请求（例如 `extra_body = { thinking = { type = "disabled" } }`）。
DeepSeek 使用 `json_mode = "json_object"`，不设置 `reasoning_effort`（包括 `none`），
通过上述 `extra_body` 关闭思考；完整可取消注释示例见 `twin.toml.example`。

评委由 `[[judges]]` 配置产生；未配置时回退 `[llm]`，不随聊天模型改变。
评委身份为 `j0:模型名`、`j1:模型名` 等，同名模型占不同位置仍是不同评委。
评分沿用原评测脚本的通用措辞：

- fact / update 的 add、modify：关键事实正确 1；部分正确或混有错误 0.5；错误、未答或编造 0。
- update 的 delete：使用与 unanswerable 相同的拒答检查。
- unanswerable：没有编造具体事实 1；编造 0。
- style：persona（口吻、身份视角、观点与价值判断）及 quality 各 1–5。
- general：quality（准确、完整、切题、清晰）1–5。

style 的两个指标各有独立评委调用，保留各自失败行。不合规分数作为评委失败，
不会当作零分。模板及控制标记（如 `<think>`、`<|im_start|>`）单独标记、计数，
不直接改变评分。评分规则版本仍为 1。

## 回答模式计数

分身适配器在 `Prediction.raw["mode"]` 保存回答模式 grounded / general / inferred / abstain；这与题目的评测
`Prediction.mode` 不同。评分规则不变。每分类及 overall 的摘要 `modes` 分别计数四种模式，直接
汇总全部重复，不平均、不依赖评委成功与否；未运行分类计数为零。比较摘要提供 A / B 各自计数，
JSON 和 Markdown 均展示。旧 records 没有 raw mode 时，按 abstain=true 计为 abstain，否则 grounded。

## 原话核验（无需评委）

从回答的 `「」`、`『』`、`“”`、ASCII 双引号中提取成对片段；嵌套片段和重复出现
分别计数，不完整的引号不计。匹配先做 NFKC、去空白及标点、拉丁字母转小写；
规范化后少于 4 个字符的术语不计。每个片段按规范化子串依次确定归类：

- **cited**：出现在回答引用的条目文本、条目证据原话或表达原文中。
- **elsewhere**：引用材料没有，但允许访问的表达原文或条目证据中有；不局限于本轮检索结果。
- **question**：前两处都没有，但出现在规范化后的题目 prompt 中；复述题目不代表声称是本人原话。
- **unverified**：材料和题目中都没有，无法核实（并不自动等于事实错误）。

复用 chat 的 `as_of` 日期边界和隐私视图，同时匹配原始文本与模型看到的假名化文本；
不把未来、无日期（指定 as_of 时）或非本人表达当作可用表达。
每分类及 overall 报告有引用的回答数、已测回答数、片段总数、四类原始计数及占比（含 `question_rate`），
直接汇总全部重复的片段，不平均重复占比、不做 bootstrap，也不依赖评委是否成功。
update 的 add / modify / delete 同样按当时的私有记忆状态核验。无片段时占比为 null；
旧 records 缺少整个计数块时不补零，显示 absent，混合记录另报 missing；仅缺少 `question`
键时按 0 处理，仍可加载和比较。片段总数必须等于四类计数之和。比较同时展示 A / B
的四类占比。`raw["quotes"]` 只保存五个计数，不另存片段文本，也不将原话、题目或回答文本记录到日志。

不报告 citation-id 有效率：chat 已经只保留本轮可引用的检索 / 核心画像 id，无引用时限制
置信度；id 合法并不能证明回答中的引号内容真是本人说过的话。

## update：受控记忆编辑

选择 update 时，用 SQLite backup API（含已提交的 WAL 数据）在
`tempfile.TemporaryDirectory()` 中创建私有数据库副本；CLI 不在真实数据库上初始化
PersonaStore。副本使用独立的 PersonaStore / PersonaChat，成功或失败后都关闭并删除。
没有真实数据库时只在临时目录中初始化空库，不创建真实文件。不重新训练模型。

每个 update item 顺序执行，item、步骤、重复及其评委调用均不并行：

1. **add**：用 document 导入的现有 `parse_text` 路径解析 add_fact，日期为今天；导入新来源，
   增量 `build_profile`，刷新 `index_persona`，独立单轮问 question，按 answer 评分。
2. **modify**：`PersonaStore.delete_source` 删除 add 来源，导入 modified_fact 的新来源；
   再增量 build、刷新检索、提问，按 modified_answer 评分。
3. **delete**：删除 modify 来源，再增量 build、刷新检索、提问；按 unanswerable 的拒答检查评分，
   应承认未知或资料中没有记录，而不是继续声称知道该事实。

每一步 build 后刷新 `p_vectors` 的 **items** 和 **expressions** 两个命名空间：chat 同时检索
画像条目与本人原文，所以即使抽取没有生成画像条目，新增文档仍须可检索；修改和删除后
清除过期条目及原文向量。聊天 `as_of=None`、`persist=False`。每个步骤在当前状态下运行
`--repeats` 次独立提问，然后进入下一步骤；原题库 id 展开为 `<id>@add`、`<id>@modify`、
`<id>@delete`，三个子题 group_id 都为原 item id。两项得到六个统计单位，而非两个。
标准答案只供每一步评委使用，不进入 chat 的输入。

运行成功时 update 与其他分类一样显示 **run**、均值与 bootstrap CI，不再产生 update
跳过警告。排除 update 时不执行记忆编辑；读取旧的跳过 update 报告仍显示 **not run**。
不支持受控编辑的自定义测试系统也保留跳过标记。构建或索引失败中止评测且隐藏异常详情；
聊天或评委失败沿用原有失败策略，不伪造零分。

固定策略 `all_judges_required`：任何评委、任何适用指标、任何重复失败，或重复
回答缺失，则该题所有指标不可用。成功题目先平均各评委，再平均重复；每题只占一个
统计单位。每分类报告题目总数、有效题数、来源组数、均值、评委失败率（失败调用 /
实际评分调用，不含 not_called）、分身失败次数及带控制标记的回答次数。

fact 按 doc_id / source 聚类，update 的三个子题按原 item id 聚类，其余分类按题目 id 聚类。
bootstrap 重采样整个来源组，
每轮按抽到的题目数加权；2000 次，确定性种子，95% percentile 区间。少于两个非空
来源组时区间为 null，不伪造确定性。重复、评委调用不是独立题目。

比较统计 **B − A**，同 id 必须有相同题目、标准答案、分类及来源分组，persona 参考
文本哈希也必须一致。每指标仅配对双方有效题目，沿用来源分组 bootstrap 差值，并报告
B 胜 / B 负 / 平数、不可配对数及双方原始统计。这不是再调用模型的盲评；所有比较
无需网络。双方独有题目仅计数，不加入配对均值。新旧 update 报告可以比较；
仅双方共有且有效的子题参与 update 差值，旧的原 item id 不会被当作已执行的子题。

## 契约兼容决定

`evals.schema.SCHEMA_VERSION` 升为 **2**。新场景使用 `QuestionInput`、
`QuestionExpected`、`QuestionOutput`，场景为 personal。预发布 P3 移除了未用于本人评测的
旧 biography payload 与 decision/stance/voice/trap 分类；旧 biography records 不再支持。
这不影响用户数据库读取。personal 记录仍保留原 schema_version，`eval-compare` 只接受单系统 personal 场景。
