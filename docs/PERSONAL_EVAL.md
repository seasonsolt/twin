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

`--categories fact,unanswerable,style,general` 可过滤分类，也可重复该选项。
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
参考文本。每次重复是独立单轮对话；不持久化聊天日志，不编辑记忆。评测错误隐藏
后端异常详情，进度及调用追踪不包含题目或回答文本；records 含完整题目及回答。

评委由 `[[judges]]` 配置产生；未配置时回退 `[llm]`。
评委身份为 `j0:模型名`、`j1:模型名` 等，同名模型占不同位置仍是不同评委。
评分沿用原评测脚本的通用措辞：

- fact / update：关键事实正确 1；部分正确或混有错误 0.5；错误、未答或编造 0。
- unanswerable：没有编造具体事实 1；编造 0。
- style：persona（口吻、身份视角、观点与价值判断）及 quality 各 1–5。
- general：quality（准确、完整、切题、清晰）1–5。

style 的两个指标各有独立评委调用，保留各自失败行。不合规分数作为评委失败，
不会当作零分。模板及控制标记（如 `<think>`、`<|im_start|>`）单独标记、计数，
不直接改变评分。update 保留契约和评分规则，但整个分类显示 **not run**：需要受控
记忆编辑；不会调用分身或评委。

固定策略 `all_judges_required`：任何评委、任何适用指标、任何重复失败，或重复
回答缺失，则该题所有指标不可用。成功题目先平均各评委，再平均重复；每题只占一个
统计单位。每分类报告题目总数、有效题数、来源组数、均值、评委失败率（失败调用 /
实际评分调用，不含 not_called）、分身失败次数及带控制标记的回答次数。

fact 按 doc_id / source 聚类，其余分类按题目 id 聚类。bootstrap 重采样整个来源组，
每轮按抽到的题目数加权；2000 次，确定性种子，95% percentile 区间。少于两个非空
来源组时区间为 null，不伪造确定性。重复、评委调用不是独立题目。

比较统计 **B − A**，同 id 必须有相同题目、标准答案、分类及来源分组，persona 参考
文本哈希也必须一致。每指标仅配对双方有效题目，沿用来源分组 bootstrap 差值，并报告
B 胜 / B 负 / 平数、不可配对数及双方原始统计。这不是再调用模型的盲评；所有比较
无需网络。双方独有题目仅计数，不加入配对均值。

## 契约兼容决定

`evals.schema.SCHEMA_VERSION` 升为 **2**。新场景使用 `QuestionInput`、
`QuestionExpected`、`QuestionOutput`，场景为 personal。为架构要求的旧 records 可读性，
保留明确标记为兼容用的 v1 biography 类型和枚举，以及联合读取契约；v1 文件不改写
或重新解释，原版本和字段可无损 round-trip。新评测不使用这些旧类型。
`eval-compare` 只接受单系统 personal 场景，不拿归档 biography 记录冒充本人评测。
