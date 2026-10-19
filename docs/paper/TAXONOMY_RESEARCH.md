# 人格分类的查新与原创性判断（长期研究课题，第一阶段）

课题：twin 的 9 维度 39 细项人格分类（`src/twin/persona/dimensions.py`，
[PERSONA_DIMENSIONS.md](../PERSONA_DIMENSIONS.md)）有没有学术原创性，对分身有没有实际用处。

第一阶段（2026-10-19）交付三样东西：

1. 查新：和这套分类相近的已有工作，逐个对照（第 2 节），以及原创性判断（第 3 节）。
2. 消融实验方案，只写方案、不运行：[TAXONOMY_ABLATION.md](TAXONOMY_ABLATION.md)。
3. 可能产生学术原创性的方向，以及每个方向需要的证据和工作量（第 4 节）。

书目信息的核对方式写在每条文献后面（标记见第 2 节开头）；"只在他人参考文献中查到"或"来自检索结果"表示没有
打开一手记录。分类相关的心理学文献（McAdams、Schwartz 等）见 [REFERENCES.md § E](REFERENCES.md)。

## 1. 分类的来历和现状

- **来历。**2026-10-03 和项目负责人讨论后定下，事先没有做文献推导，最早面向管理者（细项里有对上、对下、授权）。
  10-06 改成面向普通人的说法（taxonomy v1）；10-13 的 taxonomy v2 起，D9 生活与喜好不再需要授权，代码里保留了
  授权开关（`Dimension.consent_required`）。
- **事后对应文献。**9 个维度里 7 个能对应到心理学或语言学里的已有概念（McAdams 的三层次、Schwartz 价值、
  前景理论、GDMS 决策风格、语言风格、人际环形模型、冲突风格、个人项目）；D5 擅长什么、D9 生活与喜好没有
  对应概念，来自个性化产品的做法；1.1、1.4、2.2–2.4、3.4–3.5、4.3 这 8 个细项没有对应文献。详见
  [REFERENCES.md § E](REFERENCES.md)。
- **分类在代码里起的作用**（详见 [TAXONOMY_ABLATION.md § 1](TAXONOMY_ABLATION.md)）：抽取提示词里的清单、
  按细项分桶合并、作答时每维度 2 条核心画像、D6 风格结论必须是本人原话、覆盖报告。维度的变化速度标签
  （slow / medium / fast）除了 D8 只看最近 90 天以外，代码里没有用到。
- **没有证据表明分类有用。**现有成绩提升都来自作答模型（同一档案换 Sonnet 作答：LongMemEval 75%→94%，
  PersonaMem-v2 55%→66%）和抽取提示词（persona-v5→v6，留出集关键事实召回 75.6%→94.2%），没有做过分类消融。

## 2. 查新：已有工作怎么分类，和 twin 有哪些异同

检索日期 2026-10-19，四个方向分头检索（角色扮演与人设评测；真人模拟与数字孪生；个性化基准与记忆框架；
机制的已有工作），共核对约 60 项。每条后面的方括号是核对方式：

- **[PDF]**：下载原文，读了所列章节。
- **[HTML]**：读了 arXiv HTML 全文的所列章节。网页由抓取工具转述，类目名可能有个别措辞偏差，逐字引用前要对照原文。
- **[摘要]**：只读过 arXiv 摘要页或项目主页，**没有读正文**。
- **[代码]**：读了开源仓库的源码文件。
- **出处**：会议或期刊写明是怎么确认的。"按 arXiv 备注"表示只看了 arXiv 页面上作者写的备注，没有打开会议页面；
  没有写出处的按预印本处理。

### 2.0 先分清两条分类轴

对照时最容易混的是两条不同的轴：

- **内容主题轴**：按"关于这个人的什么"分，如价值观、说话方式、兴趣。twin 的 9 维度 39 细项在这条轴上。
- **记忆形态轴**：按"这条记忆是什么形态"分，如情景（事件）、语义（抽象事实）、程序（怎么做），或按存储层级、介质分。
  twin 在这条轴上有两层：表达层存逐字原话（接近情景记忆），画像层存按细项合并的结论（接近语义记忆），两层用
  "每条结论附 1–3 段核对过的原话"连起来。

记忆框架和记忆综述几乎都只在形态轴上分类；人设、画像和评测工作在主题轴上。所以"记忆框架里没有 twin 这样的
分类"不等于"没人做过这样的分类"。

### 2.1 角色扮演与人设评测

| 工作 | 书目与核对 | 怎么分 | 和 twin 相同 | 和 twin 不同 |
| --- | --- | --- | --- | --- |
| CharacterEval | Tu et al., ACL 2024 long, 2024.acl-long.638（ACL 版 7 位作者，arXiv v2 只列 4 位），arXiv:2401.01275。[HTML] §1、§3、§5；出处来自检索结果中的 Anthology 条目 | 13 个指标分 4 类：Conversational Ability（Fluency、Coherency、Consistency）；Character Consistency（Knowledge-Exposure / Accuracy / Hallucination、Persona-Behavior、Persona-Utterance）；Role-playing Attractiveness（Human-Likeness、Communication Skills、Expression Diversity、Empathy）；Personality Back-Testing（MBTI） | Persona-Utterance≈D6；Empathy≈7.2；Knowledge≈D1、D5 | 虚构角色（77 个，百度百科）；是给回复打分的评测指标，不组织记忆；无价值、决策、近况；无证据绑定 |
| RoleLLM / RoleBench | Wang (Zekun Moore) et al., Findings of ACL 2024, 2024.findings-acl.878, arXiv:2310.00746。[HTML] §2.1、§2.3、§4.1、附录 B–C；出处核对了 Anthology 页面 | 档案：role description、catchphrases、structured dialogues；能力两类：Speaking style imitation（Lexical Consistency、Dialogic Fidelity）和 Role-specific knowledge（Script-Based、Script-Agnostic） | Lexical Consistency≈6.1；Script-Based≈1.2–1.3；Script-Agnostic≈D5 | 只有"风格+知识"两类；影视角色；示例对话用作风格示范，不作结论证据 |
| Character-LLM | Shao, Li, Dai, Qiu, EMNLP 2023（按 arXiv 备注），arXiv:2310.10158。[HTML] §3–4、附录 A | 评测 5 维：Memorization、Values、Personality、Hallucination、Stability；训练时构造 Protective Experience 让角色说"不知道" | Values≈D2；Personality 跨 D4/D6/7.5；Protective Experience 和弃权思路相近 | 历史/虚构人物，经历由 LLM 扩写，无原话证据；靠微调实现"不知道" |
| CharacterBench | Zhou (Jinfeng) et al., AAAI 2025（按 arXiv 备注），arXiv:2412.11912。[HTML] §3–4 前半、附录抽取提示词 | 6 方面 11 维：Memory；Knowledge（Fact Accuracy、Boundary Consistency）；Persona（Attribute、Behavior）；Emotion（Self-regulation、Empathetic Responsiveness）；Morality；Believability。每维另标 sparse / dense | Attribute≈1.1、3.5；Behavior≈D6；Emotion≈7.5、7.2；Boundary≈5.3 和弃权 | sparse/dense 是"该特征在回复里出现的频率"，不是 twin 的"变化速度"，但同样是给维度加第二个标签；评测用 |
| InCharacter | Wang (Xintao) et al., ACL 2024 long, 2024.acl-long.102, arXiv:2310.17976。[HTML] §3–5、附录 B–D | 用 14 个心理量表（BFI、16Personalities、EPQ-R、Dark Triad、BSRI、CABIN、ECR-R、GSE、LOT-R、Love of Money、EIS、WLEIS、Empathy 等）**访谈**角色，再把回答换算成分 | 量表覆盖 7.2、7.5、D7、9.1、D2 的一部分；"访谈优于让角色自选选项"与"行为优先于自述"同向 | 产出是特质分数，不带证据；评测方法；虚构角色 |
| PersonaGym | Samuel et al., Findings of EMNLP 2025, 2025.findings-emnlp.368, arXiv:2407.18416。[HTML] §2–4、附录 A、D；出处核对了 Anthology | 5 个任务：Expected Action、Linguistic Habits、Persona Consistency、Toxicity Control、Action Justification | Linguistic Habits≈D6；Expected Action / Action Justification≈D3 | persona 只有一句话；维度是任务类型 |
| PersonaChat | Zhang (Saizheng) et al., ACL 2018, P18-1205, arXiv:1801.07243。[PDF] §3.1–3.2、表 1；出处核对了 Anthology | 无分类：每个 persona 是 ≥5 句第一人称事实句 | 内容多落在 D9、9.3、1.1 | 无结构；众包虚构 |
| Persona Hub | Ge et al., arXiv:2406.20094（"Work in progress"，未见正式发表）。[HTML] §1–2、§4.1 | 无字段 schema，persona 是 1–2 句自由文本；只有 Persona-to-Persona 的关系类型 | 关系扩展≈D7、1.4 | persona 是合成数据的视角，不模拟具体的人 |
| Two Tales of Persona（综述） | Tseng et al., Findings of EMNLP 2024（按 arXiv 备注），arXiv:2406.01171。[HTML] 目录和 §2–5 | 按研究领域分（Role-Playing / Personalization），不给 persona 的属性清单 | twin 正好跨两条线：资料来自真人（personalization），但要以本人身份说话（role-playing）；§5.2 把长上下文 persona 列为挑战 | 不构成维度分类的先例 |
| From Persona to Personalization（综述） | Chen (Jiangjie) et al., TMLR 2024（PDF 页眉 "Published in TMLR (10/2024)"），arXiv:2404.18231。[PDF] §2–3、§6.1；[HTML] §5.2–5.4、§6；后半（§7）未读 | persona 三类：Demographic / Character / Individualized；角色忠实度：浅层 linguistic style、knowledge（含 identity、social relationships、experiences），深层 personality、thinking process（含 decision-making）；individualized persona 的数据分 profile / interactions / domain knowledge，并明确列出 digital clones | knowledge≈D1+D5，linguistic style≈D6，personality≈D7，thinking/decision≈D3+D4；指出真人 persona "may change over time" 是未解决问题 | 用于评测，不是记忆组织；价值、近况、生活没有单列 |
| PeaCoK | Gao (Silin) et al., ACL 2023 long（Outstanding Paper），2023.acl-long.362, arXiv:2305.02364。[PDF] §3、§4.1；出处来自检索结果中的 Anthology 条目 | 5 种关系：Characteristic、Routine or Habit、Goal or Plan、Experience、Relationship；每条事实另标 intrinsic/extrinsic、one-off/regular、past/present/future 等。依据设计学 persona 文献和 Dunbar et al. 1997 的日常话题分类；有意排除 culture、politics、religion 和 emotion | Routine≈9.2，Goal/Plan≈8.1–8.2，Experience≈1.2–1.3，Relationship≈D7；**给事实加时间属性**与 twin 的变化速度标签思路相近 | 对象是职业类型的常识 persona（singer、waiter），不是具体的人；时间标在单条事实上，不在维度上；twin 收录了它排除的立场（3.5）和情绪（7.5） |
| CharacterGLM | Zhou (Jinfeng) et al., arXiv:2311.16832（"Work in progress"；据称有 EMNLP 2024 Industry 版本，**未核实**）。[HTML] §2.1–2.2、§4.1 | 属性：Identities、Interests、Viewpoints、Experiences、Achievements、Social relationships、Other（技能）；行为：linguistic features、emotional expressions、interaction patterns | **角色扮演文献里和 twin 字段重合最多的一套**：1.1、9.1、3.5/5.2、1.2–1.3、D7、5.1、D6、7.5、6.4/7.3 都有对应 | 缺 D2 价值排序与底线、D3 决策风格、D4 思维方式、D8 近况；开发者手写，无证据、无时间 |
| CroSS | Yuan (Xinfeng) et al., EMNLP 2024（按 arXiv 备注 "camera-ready"，主会还是 Findings **未核实**），arXiv:2404.12726。[HTML] §3.2、§4、§6.2 | 从小说归纳人物画像，4 维：Attributes、Relationships、Events（按时间）、Personality；外在评测是动机识别 | 任务形态最像 twin：从长文本由 LLM 归纳一个人的画像并按维度检验 | 只有 4 维；小说人物；只比一致性，不要原话证据 |
| Character is Destiny / LifeChoice | Xu (Rui) et al., Findings of EMNLP 2025, 2025.findings-emnlp.813（正式版标题与 arXiv v2 不同），arXiv:2404.12138。[HTML] §3–5；出处核对了 Anthology | 决策动机：character-driven（Personality and Traits、Emotions、Social Relationships、Values and Beliefs、Desires and Goals）和 plot-driven；档案 = description + 检索出的原文段落 | 直接对应 D3；"描述 + 原文记忆"双层结构和 twin 相似 | 原文只在推理时检索，不做核对；小说人物 |
| TimeChara | Ahn et al., Findings of ACL 2024（按 arXiv 备注），arXiv:2405.18027。[HTML] §3–5 | 把评测分成 spatiotemporal consistency（随时间变）和 personality consistency（不随时间变） | 与 twin 的 slow / fast 区分相似 | 处理的是"故事某时间点角色知道什么"（知识截断），不是真人特征多快过时 |
| SocialBench | Chen (Hongzhan) et al., Findings of ACL 2024（按 arXiv 备注），arXiv:2403.13679。[HTML] §3、§5.1 | 个体层（Style、Knowledge、情境理解、情绪识别、短/长对话记忆）和群体层社交偏好 | 群体偏好≈7.3–7.4 | 评测维度 |
| RoleEval | Shen (Tianhao) et al., arXiv:2312.16132（正式发表**未核实**）。[摘要] | 角色知识 4 维：personal information、relationships、abilities、experiences | ≈1.1、D7、D5、1.2 | 考模型对公众人物的先验知识 |
| CoSER | Wang (Xintao) et al., ICML 2025（PMLR 267，来自检索结果，未打开 PMLR 页），arXiv:2502.09082（v3 改了标题）。[HTML] §3–4 | 档案含 background、experiences、personality、motivations、relationships、character arcs；消息分 speech / action / internal thought | character arcs 与"会变"相关 | 文学角色；原文不作为结论证据 |
| Beyond Profile / CharacterBot | Wang (Zixiao) et al., Findings of ACL 2025（按 arXiv 备注），arXiv:2502.12988。[HTML] §1、§3–6、Limitations | 以鲁迅的 17 部杂文集为资料，persona 分 linguistic patterns 和 thought patterns 两层；微调（CharLoRA） | 少有的以**真人本人文字**为资料的工作；两层≈D6 和 D2/D4 | 已故公众人物、公开出版物；参数化路线，推理时不引用原文 |
| RPA 评测设计指南（综述） | Chen (Chaoran) et al., Findings of ACL 2025, 2025.findings-acl.938（arXiv 版多一位作者 Yanfang Ye），arXiv:2502.13012。[HTML] §4.1–4.3；出处核对了 Anthology | 从 1,676 篇论文归纳 6 个 agent 属性：Activity History、Belief and Value、Demographic Information、Psychological Traits、Skill and Expertise、Social Relationships | 可作为领域共识的外部参照：1.1、1.2/9.2、D2、D4/7.5/9.1、D5、D7 都有对应 | 决策归为任务属性、说话方式并入社会关系；没有近况 |

### 2.2 真人模拟、个人数字孪生、个人 AI 画像

| 工作 | 书目与核对 | 怎么分 | 和 twin 相同 | 和 twin 不同 |
| --- | --- | --- | --- | --- |
| Park et al. 2024 的访谈提纲（American Voices Project） | Park, Zou, Kamphorst et al.（11 人），*LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals*，arXiv:2411.10109（v1 2024-11-15，v3 2026-06-28；v1 标题 *Generative Agent Simulations of 1,000 People* 未回查 v1 页面），无正式出处。[PDF] v3 正文与补充材料 Table 7 全表；AVP 领域来自 Stanford Center on Poverty and Inequality 方法页（抓取转述） | AVP 官方 12 个领域：life history、rhythm of everyday life、relationships、economic hardship、income and expenses、jobs、safety net、neighborhood、health、mental health/stress、political beliefs、key identities and sources of meaning。Park 用删节版（99 个固定问题，Table 7 无板块小标题）；agent 端的"expert reflection"按 psychologist / behavioral economist / political scientist / demographer 四个视角写观察 | 人生故事≈1.2–1.3，日常节奏≈9.2，关系≈D7/9.3，健康≈9.4，政治≈3.5，意义与价值≈1.1/2.1 | **没有 D4、D5、D6 的题**，D3 只有"人生岔路口"一组；有经济、救助、住所等 twin 没有的领域；整份逐字稿放进上下文，不按维度整理；一次访谈、不处理冲突、强制作答。另外 Park 特意选了**和评测无关**的提纲，twin 的分类和评测题单不是独立的 |
| Second Me 与 LPM 1.0 | Wei (Jiale) et al., *AI-native Memory 2.0: Second Me*, arXiv:2503.08102；Shang (Jingbo) et al., *AI-native Memory: A Pathway from LLMs Towards AGI*, arXiv:2406.18312。[PDF] 两篇的方法章节；[代码] `mindverse/Second-Me` 的 `lpm_kernel/L1/bio.py`、`prompt.py`、`shade_generator.py`（HEAD d0e4025） | 三层：L0 原始数据（RAG）、L1 自然语言记忆（Bio、Topics、Preferences、Social Connections，按粒度分 Summarized Sentences / Tags / Global）、L2 参数记忆（个人 LoRA）。代码里的 shade 是**记忆向量聚类自下而上长出的兴趣领域**，带时间线（`refMemoryId`）和 5 档置信度；status bio 分 Recent（1 天）/ Earlier（7 天）和身心状态。"shades"一词只出现在代码里 | 总体描述、近况一节、结论挂记忆编号、置信度、增量更新 | **没有固定维度**，画像天然偏兴趣（9.1）和熟悉领域（D5）；证据指向整条记忆，不引原话、不核对；要求 L1 句子不互相矛盾（twin 保留矛盾）；不弃权；主要用来生成微调数据 |
| Twin-2K-500 | Toubia, Gui, Peng, Merlau, Li, Chen, arXiv:2505.17479；Marketing Science 期刊版 DOI 10.1287/mksc.2025.0262 来自检索结果，出版社页面 403，**卷期未核实**。[PDF] v1 第 1–6 页（含 Table 1） | 7 个板块：Demographics、Personality Traits（Big 5 等约 20 个量表）、Cognitive Abilities、Economic Preferences（博弈、折现、风险/损失厌恶）、Heuristics and Biases（被试间、被试内）、Product Preferences | 风险/损失厌恶≈3.1，折现≈3.2，信任博弈≈2.4，价值量表≈2.1，Need for closure / Maximization≈3.4/4.4 | 全是标准化量表和实验，是测量工具清单；无说话方式、近况、经历；无证据 |
| Digital Twins as Funhouse Mirrors | Peng, Gui, Brucks, Merlau et al., arXiv:2509.19088。[摘要] | 19 项预注册研究：基于 500 题建的孪生和本人平均只有 r=0.20 的相关；五种失真：insufficient individuation、stereotyping、representation bias、ideological bias、hyper-rationality | 是"资料不足就弃权、不用刻板印象补齐"的动机证据 | 不是分类工作 |
| Generative Agents | Park et al., UIST 2023, doi:10.1145/3586183.3606763, arXiv:2304.03442。[PDF] §4.1–4.2、附录 A–B | 记忆流三种对象：observation、reflection、plan；反思格式 "insight (because of 1, 5, 3)" 并**存被引记录的指针**；摘要描述含核心特质 / 当前在做的事 / 对近况的感受 | **"结论挂证据"的早期先例**；摘要描述粗略对应 D1–D7 / 8.2 / 8.3 | 虚构角色；无固定维度；证据是记录编号，不核对原话；不弃权 |
| Personal LLM Agents（综述） | Li (Yuanchun) et al.（28 人），arXiv:2401.05459。[PDF] §3.1–3.2、§4.3 | 用户感知分 short-term（作息、健康、情绪、压力）和 long-term（profile、personality）；智能等级 L1–L5，L5 "Autonomous Avatar" | 短期/长期两分与变化速度相近；L5 可作 twin 定位的引用 | 系统架构分类，没有内容维度 |
| TwinVoice | Du (Bangde), Guo et al., arXiv:2510.25536；ACL 2026 Findings（2026.findings-acl.981，来自检索结果，**未打开 Anthology**）。[摘要] + HTML 抓取转述 | 三个场景：Social / Interpersonal / Narrative Persona；六项能力：Mindset Coherence（Opinion Consistency、Memory Recall、Logical Reasoning）、Linguistic Expression（Lexical Fidelity、Persona Tone、Syntactic Style） | 3.5、1.3、D4、6.1–6.3；社交/私聊区分≈6.4/6.5 | 评测；历史是原帖原话，不整理成画像 |
| DeepPersona | Wang (Zhen) et al., arXiv:2511.07338（NeurIPS 2025 主会还是 workshop **未核实**）。HTML 抓取转述，**附录原表未亲读** | 从约 6.2 万条用户–ChatGPT 问答抽属性，得到 8,496 个节点的层级树；人工定 12 个一级类：Demographic、Physical and Health、Psychological and Cognitive、Cultural and Social Context、Relationships、Career、Education、Hobbies/Interests/Lifestyle、Daily Routine、Core Values/Beliefs、Emotional and Relational Skills、Media Consumption | **本次找到的、面向 LLM 的"了解一个人需要哪些维度"分类里最接近的一个**：1.1、9.4、D4/7.5、D7/9.3、D5、1.2、9.1、9.2、D2、9.5 都有对应 | 没有单独的 D3 决策、D6 说话方式、D8 近况；用于合成虚构 persona，不从真人资料整理记忆 |
| AlignX | Li (Jia-Nan) et al., arXiv:2503.15463。[摘要] + HTML 抓取转述（Table 7） | 90 维偏好空间：心理学模型（Big Five、Maslow、Murray）、对齐偏好、43 个内容兴趣标签 | D2、9.1、9.5 | 用于偏好对齐（回答合谁的口味），不描述一个人 |
| 人类数字孪生综述 | Lin (Yujia) et al., arXiv:2212.05937（期刊版**未打开**；正文说数据"eight categories"、表里只列 5 类）；Lauer-Schmaltz et al., arXiv:2402.07922。[PDF] 摘要和分类章节 | 以传感器和生理数据为中心：physical、behavioral、social、physiological、psychological、cognitive 等；HDT 分 human-in-the-loop / physiological / mechanistic / cognitive | 只有 9.2、9.4 和社交量 | "人类数字孪生"在工程界主要指医疗和工业场景 |
| McAdams, Life Story Interview – II | McAdams, Foley Center, Northwestern University, Revised 2007。[PDF] 全文 5 页 | A Life Chapters；B Key Scenes（高峰、低谷、转折、童年、成人、宗教、智慧事件）；C Future Script；D Challenges；E Personal Ideology（宗教/伦理价值、政治/社会价值、观点变化、单一价值）；F Life Theme；G Other | A、B≈1.2–1.3；E≈D2、3.5；D≈7.5、9.4 | 只关心叙事认同，没有 D4–D7、D9 |

### 2.3 个性化基准的用户画像，和记忆框架的记忆类型

| 工作 | 书目与核对 | 怎么分 | 和 twin 相同 | 和 twin 不同 |
| --- | --- | --- | --- | --- |
| PersonaMem v1 | Jiang (Bowen) et al., *Know Me, Respond to Me*, COLM 2025（按 arXiv 备注），arXiv:2504.14225。[HTML] §2–4.1、附录 D.2、G | 画像：name、age、gender、race、occupation + 事件时间线，属性分 static / dynamic；7 种查询类型（Recall user-shared facts、Track full preference evolution、Revisit reasons behind preference updates 等）；15 个场景话题（附录 B 写 18 个，原文前后不一致） | static/dynamic 与变化速度相近；"追踪偏好演变"和保留矛盾、D8 有关 | 话题按助手使用场景分，多落在 D9、D7；没有 D3、D4、D5、D6 |
| PersonaMem-v2 | Jiang (Bowen) et al.（16 人），arXiv:2512.06688，未列正式出处。[HTML] §2.1–2.3、§3.2、§4 | 开放人设字段：demographic、professional/educational、personal characteristics、relationships、values and beliefs、technological familiarity、conversational styles、mental and physical health；偏好按刻板程度和敏感度分；记忆是每人一份 ≤2,048 token 的文本，无分区 | 1.1、D2、D6、D7、9.4 | 没有决策、思考、擅长与不懂、近况；"隐式流露"是考推断能力，不是合并规则 |
| LongMemEval | Wu (Di) et al., ICLR 2025（按 arXiv 备注），arXiv:2410.10813。[HTML] §3.2、§5.3、附录 A.1 表 5 | 5 种能力（information extraction、multi-session reasoning、temporal reasoning、knowledge updates、abstention）；用户属性本体 5 类 164 个：Demographic Information、Lifestyle、Situational Context、Life Events、Belongings | 1.1、D9、1.2、D8；abstention≈弃权 | 只覆盖事实型生活信息，没有价值、决策、思考、说话、相处 |
| LaMP / LongLaMP、LoCoMo、PrefEval | LaMP：Salemi et al., ACL 2024；LoCoMo：Maharana et al., ACL 2024（出处来自他人引用）；PrefEval：Zhao (Siyan) et al., ICLR 2025, arXiv:2502.09597。均为 [摘要] 加部分 HTML | 按任务（LaMP）、QA 类型（LoCoMo）、偏好显式/隐式和 20 个话题（PrefEval）分 | PrefEval 的显式/隐式和"自述/行为"相关 | 画像就是历史文档或话题，没有人格内容分类 |
| MemoryOS | Kang (Jiazheng), Ji, Zhao, Bai, EMNLP 2025 main, 2025.emnlp-main.1318（核对了 Anthology），arXiv:2506.06326。[HTML] §3.1–3.3；[代码] `BAI-LAB/MemoryOS` 的 `prompts.py` | 形态轴三层：短期、中期、长期个人记忆；长期里的 User Traits 自称"90 dimensions"，分 basic needs and personality（Big Five、Maslow 需求等）、AI alignment、content platform interest tags（代码里数到约 51 条，和"90"不符，**待人工核对**） | **主题轴上本次找到的最细的用户画像 schema**；兴趣≈9.1，家庭≈9.3，健康≈9.4，Language Style / Sense of Humor≈D6 | 给用户打分打标签，没有 D3 决策、D4 思考、D2 底线原则、D5、D8；无证据、无矛盾标注 |
| Mem0 | Chhikara et al., arXiv:2504.19413。[HTML] §2 | 操作：ADD / UPDATE / DELETE / NOOP；抽取提示词列出 7 类个人信息 | 1.1、D5、D8、D9 的一部分 | 矛盾时**删除**旧记忆，和"保留并标出"相反 |
| Zep / Graphiti | Rasmussen et al., arXiv:2501.13956（出处未列）。[HTML] §2.2 | 形态轴：episode / semantic entity / community 三层子图；语义边从 episode 抽取并保留原始消息 | 结论关联原始消息 | 矛盾时把旧边标为失效（按时间新覆盖旧），不按证据类型、不展示矛盾；不逐字核对 |
| MIRIX、MemGPT/Letta、A-MEM、MemOS、CoALA 及记忆综述 | MIRIX：Wang (Yu), Chen (Xi), arXiv:2507.07957；MemGPT：Packer et al., arXiv:2310.08560；CoALA：Sumers et al., TMLR 2024, arXiv:2309.02427；综述含 Hu et al. *Memory in the Age of AI Agents* 等。[摘要] 或 [HTML] 定义章节 | 全部在形态轴上：MIRIX 的 Core / Episodic / Semantic / Procedural / Resource / Knowledge Vault；MemGPT 的 core / recall / archival；CoALA 的 working / episodic / semantic / procedural | twin 的表达层≈episodic / resource，画像层≈semantic | 关于用户的信息最多是一个 `human` 块或"用户事实"大类，**内部不再按主题细分** |
| ChatGPT 记忆 | OpenAI 产品，非论文；官方 FAQ 返回 403，只有第三方用提示词诱导出的四段结构 | 未能核实 | — | 不引用 |

### 2.4 机制的已有工作

| 机制 | 最接近的已有工作（核对方式） | 判断 |
| --- | --- | --- |
| 结论附 1–3 段逐字核对的原话，核对不过就丢 | GopherCite（Menick et al., arXiv:2203.11147, 2022，逐字引文；[PDF] §2）；Anthropic Citations API（接口保证引文是原文片段）；Generative Agents 的反思存证据指针（[PDF]）；Zep 保留原始消息；Second Me 的 `refMemoryId`（[代码]）；DeLucia et al. arXiv:2401.06742 用 NLI 过滤不被对话支持的人设条目（[摘要]）；An, *Fidelity Before Structure*, arXiv:2601.00821（2025-12 v1，2026-07 v4）抽取提示词要求附 "EXACT verbatim quote"，并发现逐字原文比有损抽取物在 LoCoMo、LongMemEval-S 上高 16–22 个点（[摘要]，附录提示词只做了文本检索）；Wu & Zhu, *Agent Zero Memory*, arXiv:2608.29606（2026-08-30）每条记忆带证据指针，回答只能引用打开过的证据，否则弃权（[摘要]） | **部件都有先例，组合没检索到**：在个人画像**抽取阶段**要求每条结论附逐字原话、由程序核对、失败就丢，并作为系统约束评估 |
| 行为证据优先于自述，矛盾保留并标出 | 理论：Samuelson 1938 显示性偏好、LaPiere 1934 态度—行为不一致、Nisbett & Wilson 1977 内省局限、Fleeson 2001 行为密度分布（DOI 经 Crossref 核对）；SOKA（Vazire 2010）只能当类比，且提示内在状态上自评更准。系统：Mem0 删除、Zep 标失效，都是"新的覆盖旧的"；Yang (Lu) et al., *TANGLE*, arXiv:2608.13921（2026-08-14）把个人记忆冲突分为情境分区、行为振荡、来源矛盾，主张保留冲突、不强行给单一答案（[摘要]；"来源矛盾包括自述和行为推断"来自 §3.2 的抓取转述，摘要里没有） | **部分已有，组合没检索到**：按证据类型排优先级、同时把矛盾展示给本人。TANGLE 是最近的近邻，而且认为固定的优先规则不够，论文里必须正面回应 |
| 按内容哈希增量重建，版本变了才重整 | Nix（Dolstra et al. LISA 2004）、Build Systems à la Carte；LlamaIndex 文档哈希、GraphRAG 按提示词缓存（工程文档，只看了检索转述）；LightRAG 把增量更新作为论文贡献但只处理新增 | **已有成熟做法**，不构成原创 |
| 资料没有就弃权，三模式加置信度上限 | Chow 1970 拒识、选择性分类、SQuAD 2.0、Wen et al. 弃权综述、LongMemEval 的弃权题、AbstentionBench；在真人模拟里 Park 2024 强制作答，Agent Zero Memory 有 citation lock 弃权 | 一般意义上**已有成熟做法**；在"替真人说话"的场景里用得少，general 模式明确说明"不是本人观点"这一点没有专门检索 |

## 3. 原创性判断

### 3.1 分类本身：**没有原创性可以主张**

1. **9 个维度的内容和已有分类大面积重合。**DeepPersona 的 12 个一级类、CharacterGLM 的属性加行为字段、
   RPA 评测指南综述归纳的 6 个属性、Chen et al. 综述的 knowledge / linguistic style / personality / thinking
   process、MemoryOS 的 User Traits、PersonaMem-v2 的人设字段，把 D1、D2、D5、D6、D7、D9 基本覆盖了；
   AVP 访谈提纲和 McAdams 的 Life Story Interview 覆盖了 D1 和 D2 的叙事与价值部分。审稿人会把 twin 的维度看成
   "已有分类的重组"，这个判断是对的。
2. **相对少见的只有几处，而且都谈不上新概念。**
   - 把价值（D2）、决策（D3）、思维（D4）拆成三个一等维度。多数工作把它们合成 personality / thinking 或
     belief / value 一类；但决策风格、风险与时间偏好、对不确定性的态度本身都是心理学和经济学的成熟概念
     （REFERENCES.md § E），Twin-2K-500 的量表也测了它们。
   - 5.3 自认不懂的领域、2.2 底线：在画像 schema 里没见过单列，但只是两个细项。
   - D8 最近在关注单列。Second Me 的 status bio、Generative Agents 的"当前在做的事"已经有"近况"这一块。
   - 39 个细项的粒度。比多数评测维度细，但比 MemoryOS（约 51–90 维）和 DeepPersona（8,496 个节点）粗。
     粒度本身不是贡献，除非能证明它对成绩有影响（第 4.4 节）。
3. **变化速度标签的作用被高估了。**PeaCoK 给单条事实标时态和频率，PersonaMem 分 static / dynamic，TimeChara
   区分随时间变和不变的一致性，Li et al. 综述分短期 / 长期感知。twin 是标在维度上，但代码里**只有 D8 的 90 天窗口
   用到了它**，而且只在覆盖报告里；重新整理的策略由提示词和分类版本号决定，不看速度标签。所以不能写成
   "按变化速度驱动记忆维护"。
4. **没有效度证据。**细项是否可区分、是否完整，没有测过；分类对成绩有没有作用，没有做过消融。

结论：在第二阶段的消融和效度实验给出正面结果之前，**不应在论文或商业材料里说分类是原创的或领先的**。
最多可以写："在已有角色属性和用户画像分类的基础上，为真人分身重新组织和细化的一套分类"，并附上和
DeepPersona、CharacterGLM、AVP、LSI 的逐维对照表。

### 3.2 分类的用途：有区别，但单独不足以构成贡献

- 已有工作的维度大多是**评测轴**（CharacterEval、CharacterBench、TwinVoice、PersonaGym），少数是**一次性生成或
  手写的档案字段**（CharacterGLM、PeaCoK、CroSS、DeepPersona）。twin 用分类作**记忆的组织键和合并单元**：
  从一个真人的自然资料里持续抽取，按细项合并、标矛盾、增量重建，并作为网页上本人确认的单位。这个用法在本次
  检索里没有找到相同的做法。
- 但"按主题分桶来组织用户记忆"本身不难想到，MemoryOS 的 User Traits 已经部分这样做了。用途上的区别只有在
  能证明"按这套分类组织比不分类好"时才有学术分量，所以还是要回到消融。

### 3.3 机制：可能有原创性的是**组合**，不是单个部件

| 机制 | 判断 | 能怎么写 |
| --- | --- | --- |
| 逐字核对原话、不过就丢 | 部件有先例（GopherCite、Citations API、Generative Agents、Fidelity Before Structure、Agent Zero Memory），在个人画像抽取阶段作为硬约束并评估的没检索到 | 可以写成贡献，但要引用这些先例，把增量说清楚：约束放在抽取阶段而不只是作答阶段；按"本人原话 / 他人记述"区分；有编造引语的实测数据 |
| 行为优先于自述、矛盾保留 | 理论依据成熟，系统层面 TANGLE 是近邻，按证据类型排序并展示给本人的没检索到 | **最有希望成为独立贡献**（第 4.2 节），但要回应 SOKA（内在状态上自评更准）和 TANGLE（固定规则不够） |
| 内容哈希增量重建 | 成熟工程做法 | 不写成贡献；可以写它带来的可检验性质：删除后结论确定消失、按日期回答 |
| 弃权 | 成熟做法 | 不写成贡献；可以报告它在真人模拟里的代价（Twin-2K-500 上弃权和行为预测直接冲突）|

**几个要注意的事实：**

- Park et al. 特意选了和评测无关的访谈提纲。twin 的分类、问卷（zh-v2 的 42 道细项题）和覆盖报告都出自同一个
  设计者，论文里要承认这一点。
- *Fidelity Before Structure* 的结果（逐字原文优于抽取物，二者并存时不掉分）支持 twin 保留表达层，同时也提醒：
  画像层（包括分类）对检索类基准可能没有增益，这和消融方案第 0 节的预期一致。
- 2026 年下半年相关预印本增长很快（TANGLE、Agent Zero Memory 都是 8 月的）。投稿前要再查一次。

### 3.4 这次没有覆盖或没能核实的

- 商业个人分身产品（Delphi、Personal.ai 等）没有找到可引用的方法文档。
- 中文期刊和学位论文没有检索。
- 只读了摘要或依赖抓取转述的条目（上表已注明），以及出处未核实的条目（CharacterGLM 的 EMNLP Industry 版、
  CroSS 是否主会、TwinVoice 的 ACL 2026 Findings、DeepPersona 的 NeurIPS 2025、Twin-2K-500 的卷期、
  MemoryOS User Traits 的实际条数），引用前要补读原文。

## 4. 可能产生学术原创性的方向

按"证据越硬越靠前"排列。每个方向都写明需要什么证据才能成立、要做多少工作；工作量按一个人估算。

### 4.1 证据绑定的分身记忆：每条结论附逐字核对的原话

- **主张。**分身画像里的每条结论都附 1–3 段逐字核对过的原话，核对不过的结论在抽取时就丢掉；作答时引号里的
  话再核对一次（quote guard）。这让"分身说的话是不是本人说过"成为可以机械检查的性质。
- **已有先例**（第 2.4 节）：GopherCite、Citations API、Generative Agents 的证据指针、*Fidelity Before Structure*、
  Agent Zero Memory。增量要写清楚：约束放在画像抽取阶段，核对失败的结论直接丢掉，区分本人原话和他人记述。
- **需要的证据。**(a) 查新已做，组合没检索到，投稿前再查一次；(b) 消融：去掉
  逐字核对后，有依据率、原话来源占比（cited / elsewhere / unverified）、编造引语数量的变化，多个模型；(c) 编造
  引语的基线数据已有（`gpt-5.6-sol` 运行时去掉 26 处、`deepseek-flash` 49 处），要扩到多名受试者。
- **工作量。**代码改动小（一个开关）；评测 2–3 周，主要花在多名受试者的资料和题目上。论文 OUTLINE 7.5 已列入。

### 4.2 行为证据和自述冲突：机制和理论依据

- **主张。**同一细项里，本人实际做过的事优先于本人对自己的描述；两者矛盾时保留矛盾、标出来，不替本人下结论。
- **理论依据**（书目已用 Crossref 核对，正文还没读，第二阶段要读）：显示性偏好（Samuelson 1938）；
  态度—行为不一致（LaPiere 1934）；内省报告的局限（Nisbett & Wilson 1977）；特质是行为状态的密度分布
  （Fleeson 2001）。SOKA（Vazire 2010）只能当类比，而且它提示**内在状态上自评更准**：7.5 情绪触发、2.1 价值
  这类细项不宜一律以行为为准。
- **最近的近邻**：TANGLE（arXiv:2608.13921，2026-08）把个人记忆冲突分为情境分区、行为振荡、来源矛盾，主张保留
  冲突，并认为固定的优先规则不够。twin 的规则正是一条固定规则，论文必须回应：要么证明按细项区分的固定规则
  够用，要么把规则改成按细项设定。
- **需要的证据。**(a) 一组"自述和行为矛盾"的题：同一个人既说过 X、又做过非 X，问分身"他会怎么做"，金标准是
  后来的实际行为，而不是问卷；(b) 对照五种合并规则：行为优先 / 自述优先 / 不区分 / 不标矛盾 / 按细项区分（外显行为以行为为准、
  内在状态以自述为准），也可以和 TANGLE 的 CAAP 对比；(c) 合成人物里事先埋入矛盾（OUTLINE 7.1 已计划），
  真人资料里由本人标注。
- **工作量。**合成人物数据集 2–3 周；真人标注依赖志愿者，1–2 个月。代码改动小（合并提示词规则 3）。
  这个方向既有理论根基又和分身直接相关，**是最可能写成独立贡献的一个**。

### 4.3 面向分身的分类：按"作答需要"而不是按"人格结构"组织

- **主张。**人格量表按特质结构分类（Big Five、价值），分身需要的是"回答和说话所需要的信息"：事实与经历、
  看重什么、怎么做决定、怎么说话、最近在忙什么。twin 的分类是这个思路的一个实例。
- **需要的证据。**这是最难成立的一项。必须同时有：(a) 查新显示没有面向分身/个人模拟的同类分类（第 3 节的结论
  是**已有相近分类**，见那里）；(b) 消融显示 9 维度显著优于不分类、粗分类和量表分类
  （[TAXONOMY_ABLATION.md § 6](TAXONOMY_ABLATION.md)）；(c) 分类的效度：细项之间是否可区分（不同标注者把同一
  结论归到同一细项的一致性，Cohen's κ / Krippendorff's α）、是否完整（随机抽取的结论有多少找不到合适细项）。
- **预期。**按消融方案第 0 节，(b) 大概率得不到显著结果。在 (b) 成立前，**不应把分类本身写成原创贡献**。
- **工作量。**消融完整方案约 1 周、模型费用数百美元（不含扩大样本）；效度标注要 2 名标注者各标约 300 条结论，
  约 1 周人工。

### 4.4 分类粒度和成绩的关系

- **主张。**从 1 类到 3 类、9 类、39 类、更细（比如再按 applies_when 分），成绩是单调上升、存在拐点，还是基本
  不变；粒度对抽取召回、合并重复率、建档成本各有什么影响。
- **需要的证据。**消融方案里的 T0 / T3 / T9 三点，再加一个更细的点（如把 39 细项拆到约 80 项）和一个打乱分桶的
  对照（T0c）。只有三四个点，结论只能是描述性的；要画出可信的曲线，每个点都要用足够的题（[TAXONOMY_ABLATION.md § 5](TAXONOMY_ABLATION.md) 的功效估算：
  PersonaMem-v2 至少约 250 题）。
- **价值。**即使结果是"粒度无关"，也是一个有用的负结果：说明分身记忆的分类可以按产品需要设计，不必追求细。
  这类负结果在 LLM 记忆文献里少见，可以作为论文里的一节，不太可能单独成文。
- **工作量。**在消融完整方案基础上再加 2 组，约 2–3 天、模型费用约 $150（dev 集规模）。

### 4.5 按内容哈希增量更新、资料没有就弃权

- **增量更新。**来源内容或提示词/分类版本变了才重建，合并按"模型看到的内容"缓存。这在工程上是常规做法
  （内容寻址构建）；能写成贡献的是它带来的性质：删除一条资料后，由它支持的结论确定地消失（OUTLINE 4.3、
  Table 3 的删除实验），以及按日期回答"他那天会怎么说"（`as_of`）。需要的证据是删除和 `as_of` 实验，
  OUTLINE 已列入，约 1–2 周。
- **弃权。**资料没有就弃权、置信度上限由模型之外的规则施加。弃权本身有大量已有工作（第 2.4 节）；能写的是在
  "模拟具体的人"这个场景下的代价和收益（OUTLINE Figure 2：编造率对有用性）。Twin-2K-500 的结果已经说明
  弃权和行为预测直接冲突，这要照实报告。

### 4.6 不建议投入的方向

- 把 9 维度和某个心理学量表做"对应"并声称有理论依据：事后对应不构成验证，审稿人会直接看出来。
- 用问卷评测（zh-v2）证明分类有效：42 道非人格题是按 twin 的细项出的，循环论证。
- 用变化速度标签（slow / medium / fast）做卖点：代码里几乎没有用到。

## 5. 对商业表述的建议

负责人把学术原创性看作估值的重要说法。按目前的证据，可以说和不能说的是：

- **可以说**（有代码支持，是产品事实，不是学术原创性）：每条结论都能追溯到本人的原话并经过逐字核对；行为和
  自述矛盾时保留并标出；资料没有的不编；删除资料后由它支持的结论随之消失（删除的正式实验还没跑，见 OUTLINE
  Table 3）。
- **谨慎地说**：把逐字核对、行为优先、矛盾保留组合进真人分身的画像记忆，"就我们检索所及没有见到同样的做法"。
  每个部件都有先例（第 2.4 节），要附上这句限定，投稿或对外发布前再查一次。
- **不能说**：分类是原创的、分类领先、分类经过心理学验证。查新已经找到大面积重合的分类（第 3.1 节）；"领先"
  和"有用"要等消融结果，按预期很可能得不出。
