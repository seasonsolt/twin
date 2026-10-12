# PersonaMem-v2

[PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2)（论文 arXiv 2512.06688，CC-BY-4.0，可商用，需署名）测的是从长对话里推断用户没有明说的偏好：用户只是让助手改写邮件、翻译、问知识，偏好顺带露出来，最后用一道四选一题看回答是否贴合这个人。它取代 [PersonaMem v1](PERSONAMEM.md) 作为人格与偏好的主基准；v3 为 CC-BY-NC-4.0，不能商用，不采用。

## 数据与合法输入

- 题目：`benchmark/text/benchmark.csv`，200 人、5000 道题，每人约 25 道。偏好类型 7 种：`ask_to_forget`（用户要求别记住，正确答案不能用这条偏好）、`neutral_preferences`、`anti_stereotypical_pref`、`stereotypical_pref`、`therapy_background`、`health_and_medical_conditions`、`sensitive_info`。CSV 没有题号，题号取人员编号加题干与正确答案的哈希；上游重复的几行只保留一次。
- 历史：每人一份 32k 对话 `data/chat_history_32k/…personaN.json`，放在 `benchmark.csv` 旁的同名相对路径下，只需下载抽到的人。按上游 `inference.py` 整段送入，包括开头助手的人设系统提示（人口学、性格、爱好、政治立场、价值观等概括性背景，各人字段不同；题目考的是对话里顺带露出的具体偏好，但概括背景可能帮上忙，这和上游给所有方法的输入一致）；用户发言是本人，助手与系统提示是他人。
- 题干末尾按上游追加 `Please recall my related preferences from our conversation history to give personalized responses.`

## 评分

四个答案（正确答案加三个干扰项）每题打乱一次，标为 A–D。上游用 Python 加盐的 `hash()` 作种子，不同进程顺序不同，这里改用题号派生的固定种子，正确字母随之确定。Twin 要求只回 `Final Answer: X`，用上游 `extract_final_answer` 的同一组正则取字母，取不到计为格式失败；弃权、失败都算错。

## 测试集

按人抽样，抽到的人的全部题都进集：一份档案能答约 25 道题，比按题抽样省建档。正式集 8 人（约 200 题，种子 `personamem-v2`）；开发集 4 人（约 100 题），只从正式集以外的人里抽。

```bash
uv run twin --config twin.toml eval-personamem2 --benchmark <数据目录>/benchmark.csv --split dev --out <输出目录>
```

## 公开成绩（论文，32k 选择题）

前沿大模型直接读全文约 37%–48%（GPT-5-Chat 45.6%），作者用强化微调的 Qwen3-4B 约 53%，作者的代理式记忆框架 55%（只用 2k 记忆）。这些成绩用论文自己的抽样和打乱，只能看量级。
