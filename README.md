# twin

**A personal digital twin, grounded in a person's own material.**

English | [简体中文](#简体中文)

> **Status: early.** Interfaces will still change.

twin builds a persona from someone's own material — questionnaires, chats, documents, interviews, transcripts — where every trait carries a verbatim, dated quote, and serves it as conversation and speech: **Identity → Memory upload → Service**. Answers cite their evidence or abstain; every output is labelled as AI-generated and does not represent the person. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Chinese).

---

## 简体中文

通用的个人分身：从一个人的资料里提炼出有来源依据的人格档案，再以对话、语音等方式提供服务。

```
Identity 身份  ──►  Memory upload 记忆上传  ──►  Service 服务
```

- **有据可查。** 档案里每一条都带逐字核对过的原话和日期；回答引用不到依据时降低置信度或弃权，不硬编。
- **可以"穿越"。** `--as-of` 只用某一天及以前的资料作答。
- **明确标识。** 所有输出都是 AI 模拟，不代表本人意见；语音和导出文件带显式与隐式的 AI 合成标识。
- **隐私优先。** 他人姓名在进入档案时统一化名；对他人的评价不进档案；本人资料默认不发往境外服务。

架构与规则见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 安装

需要 Python 3.12+，推荐 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
source .venv/bin/activate
```

## 使用

```bash
twin init                     # 生成带中文注释的 twin.toml，按注释填写模型和向量服务
```

密钥只放在环境变量里（`TWIN_LLM_KEY`、`TWIN_EMBED_KEY` 等），配置文件只写变量名。

**记忆上传**

```bash
twin persona import --kind questionnaire 问卷.md
twin persona import --kind chat 聊天记录.csv
twin persona import --kind document 文章/*.md
twin persona import --kind meeting 会议转写.txt      # 也支持 interview、biography
twin persona sources                                # 看已导入的资料
twin persona build                                  # 抽取并合并人格档案，只处理新增或变化的部分
twin persona coverage                               # 各维度的完成度，以及下一步该补什么资料
```

**服务**

```bash
twin persona chat "你怎么看远程办公？"
twin persona chat --as-of 2025-12-31 "那时候你怎么看？"
twin ui                                             # 本机网页：问卷、导入、档案、完成度、聊天、回放与朗读
```

**语音（可选）**

在 `twin.toml` 的 `[tts]` 里配置语音后端：自托管的 MOSS-TTS-Nano（见 [deploy/tts-moss](deploy/tts-moss/README.md)）或 Cloudflare MeloTTS（数据出境，只用于非个人数据）。

```bash
twin media speak 回复.json --out 音频目录/            # 带标识的分段语音和清单
twin media check --out 评测目录/                      # 合成句集回听评测：字错率与延迟
```

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：产品形态、分层、层间规则、治理、路线
- [docs/PERSONA_DIMENSIONS.md](docs/PERSONA_DIMENSIONS.md)：人格维度与完成度
- [docs/MEDIA.md](docs/MEDIA.md)：语音与展示通道
- [docs/CONTRACTS.md](docs/CONTRACTS.md)、[docs/WEB_UI.md](docs/WEB_UI.md)：模块与网页接口契约

## 开发

```bash
ruff check src tests deploy && ruff format --check src tests deploy
mypy
pytest -q
```
