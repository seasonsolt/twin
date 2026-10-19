# Reading list

Sections A–D were compiled without network access, from memory. **Check every title, venue and arXiv
number before citing.** Only the two papers marked "read" have been checked against the PDF.
Section E was checked online on 2026-10-19 against publisher, DOI or catalogue records; that confirms
the bibliographic details, not that the full text has been read.

PDFs go in `docs/paper/refs/` (ignored by git). Most arXiv licences allow only arXiv to redistribute,
so the repository keeps links and notes, not the files.

## Read

| Paper | Notes |
| --- | --- |
| Park et al., *LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals*, arXiv:2411.10109 (v3) | [PARK_NOTES.md](PARK_NOTES.md) |
| Wei et al., *AI-native Memory 2.0: Second Me*, arXiv:2503.08102 (v2) | [SECONDME_NOTES.md](SECONDME_NOTES.md) |
| Shang et al., *AI-native Memory: A Pathway from LLMs Towards AGI*, arXiv:2406.18312 (LPM 1.0) | Cited by Second Me; not yet read |

## A. Simulating specific real people (closest to our claim)

- Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, UIST 2023. The memory
  stream + reflection architecture the 1,052-person study builds on.
- Argyle et al., *Out of One, Many: Using Language Models to Simulate Human Samples*, Political
  Analysis 2023. The demographic-prompt baseline.
- Toubia et al., *Twin-2K-500: A dataset for building digital twins of over 2,000 people based on
  their answers to over 500 questions*, Marketing Science 44 (2025). Cited by Park; a possible public
  benchmark.
- Binz et al., *A foundation model to predict and capture human cognition* ("Centaur"), Nature 2025.
  A fine-tuned model of human choices; a counterpoint on fine-tuning.
- Horton, *Large Language Models as Simulated Economic Agents: What Can We Learn from Homo Silicus?*,
  2023.
- Lundberg et al., *The origins of unpredictability in life outcome prediction tasks*, PNAS 2024. Why
  ceilings on predicting individuals exist.

## B. Personal and agent memory (what twin is compared with)

- Packer et al., *MemGPT: Towards LLMs as Operating Systems*, 2023 (Letta).
- Chhikara et al., *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory*, 2025.
- Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory*, 2025 (Graphiti).
- Maharana et al., *Evaluating Very Long-Term Conversational Memory of LLM Agents* (LoCoMo), ACL 2024.
- Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory*, ICLR 2025.
- Salemi et al., *LaMP: When Large Language Models Meet Personalization*, ACL 2024.
- Shao et al., *Character-LLM: A Trainable Agent for Role-Playing*, EMNLP 2023. Fine-tuned personas.

## C. Evidence, citation and abstention

- Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS 2020.
- Gao et al., *Enabling Large Language Models to Generate Text with Citations* (ALCE), EMNLP 2023.
- Kadavath et al., *Language Models (Mostly) Know What They Know*, 2022.
- Ovadia et al., *Fine-Tuning or Retrieval? Comparing Knowledge Injection in LLMs*, EMNLP 2024. Direct
  support for "retrieve, don't train" facts.

## D. Risks of simulating people

- Santurkar et al., *Whose Opinions Do Language Models Reflect?*, ICML 2023.
- Wang, Morgenstern and Dickerson, *Large language models that replace human participants can
  harmfully misportray and flatten identity groups*, Nature Machine Intelligence 2025.

## E. Grounding the persona taxonomy (bibliographic details checked online)

The 9 dimensions were set in a design discussion on 2026-10-03, without a literature review
([PERSONA_DIMENSIONS.md](../PERSONA_DIMENSIONS.md)). The papers below are mapped to them after the
fact. Seven of the nine dimensions correspond to an established construct; **D5 and D9 do not**, and
several facets have no counterpart at all (listed under "Gaps"). The mapping does not validate the
taxonomy as a whole, its 39 facets or their boundaries. The prior-art search and the planned
ablation are in [TAXONOMY_RESEARCH.md](TAXONOMY_RESEARCH.md) and
[TAXONOMY_ABLATION.md](TAXONOMY_ABLATION.md).

How each entry was checked (2026-10-19): title, authors, venue, volume, pages and year against the
Crossref record of the DOI given (api.crossref.org), except where noted. This confirms the
bibliographic details only; none of these papers has been read in full for this project, and what
each "grounds" is taken from its abstract or from how other work cites it.

**Overall frame**

- McAdams, *What do we know when we know a person?*, Journal of Personality 63(3), 365–396, 1995.
  doi:10.1111/j.1467-6494.1995.tb00500.x. Three levels of knowing a person: traits, personal
  concerns, life story.
- McAdams and Pals, *A new Big Five: Fundamental principles for an integrative science of
  personality*, American Psychologist 61(3), 204–217, 2006. doi:10.1037/0003-066X.61.3.204.
  Traits, characteristic adaptations, integrative life narratives, in a cultural context.
- Vazire, *Who knows what about a person? The self–other knowledge asymmetry (SOKA) model*,
  Journal of Personality and Social Psychology 98(2), 281–300, 2010. doi:10.1037/a0017908.
  Self-ratings are more accurate for low-observability traits, ratings by others for highly
  evaluative ones. **An analogy only** for "behavioural evidence outranks self-report": SOKA compares
  two judges of a trait (the self and acquaintances), not a person's actions with their statements.

**Per dimension**

| Dimension | Paper | What it grounds |
| --- | --- | --- |
| D1 Experience and identity | McAdams 1995; McAdams and Pals 2006 | 1.2–1.3 as narrative identity (level 3). 1.1 and 1.4 have no counterpart |
| D2 Values | Schwartz, *Universals in the content and structure of values: Theoretical advances and empirical tests in 20 countries*, Advances in Experimental Social Psychology 25, 1–65, 1992. doi:10.1016/S0065-2601(08)60281-6 (the Crossref record has no volume; 25 is from other papers' reference lists) | 2.1 value priorities only; 2.2–2.4 have no counterpart |
| D3 Decisions | Kahneman and Tversky, *Prospect theory: An analysis of decision under risk*, Econometrica 47(2), 263–291, 1979. doi:10.2307/1914185 | 3.1 risk attitude |
| | Frederick, Loewenstein and O'Donoghue, *Time discounting and time preference: A critical review*, Journal of Economic Literature 40(2), 351–401, 2002. doi:10.1257/002205102320161311 | 3.2 time perspective |
| | Scott and Bruce, *Decision-making style: The development and assessment of a new measure*, Educational and Psychological Measurement 55(5), 818–831, 1995. doi:10.1177/0013164495055005017 | 3.3 and 3.6: rational, intuitive, dependent, avoidant, spontaneous styles (GDMS). 3.4–3.5 have no counterpart |
| D4 Thinking | Cacioppo and Petty, *The need for cognition*, Journal of Personality and Social Psychology 42(1), 116–131, 1982. doi:10.1037/0022-3514.42.1.116 | **Tangential.** Need for cognition is how much a person enjoys effortful thinking, not how they break problems down (4.1) or what they ask first (4.2) |
| | Freeston, Rhéaume, Letarte, Dugas and Ladouceur, *Why do people worry?*, Personality and Individual Differences 17(6), 791–802, 1994. doi:10.1016/0191-8869(94)90048-5 | 4.4 (in)tolerance of uncertainty. 4.3 has no counterpart |
| D5 Expertise | none | Knowledge and skill, not personality. Kruger and Dunning, *Unskilled and unaware of it*, Journal of Personality and Social Psychology 77(6), 1121–1134, 1999 (doi:10.1037/0022-3514.77.6.1121) does **not** ground 5.3: it shows that the least skilled overestimate themselves, i.e. that *self-claimed* competence (5.1) is unreliable. It argues for preferring demonstrated skill over self-description in 5.1, and says nothing about whether declared ignorance is accurate |
| D6 Speech | Pennebaker and King, *Linguistic styles: Language use as an individual difference*, Journal of Personality and Social Psychology 77(6), 1296–1312, 1999. doi:10.1037/0022-3514.77.6.1296 | 6.1–6.3 word use is a stable individual difference |
| | Bell, *Language style as audience design*, Language in Society 13(2), 145–204, 1984. doi:10.1017/S004740450001037X | 6.4 style shifts with the audience |
| | Biber, *Variation across Speech and Writing*, Cambridge University Press, 1988. doi:10.1017/CBO9780511621024 | 6.5 spoken versus written register |
| D7 Relationships | Wiggins, *A psychological taxonomy of trait-descriptive terms: The interpersonal domain*, Journal of Personality and Social Psychology 37(3), 395–412, 1979. doi:10.1037/0022-3514.37.3.395 | 7.1–7.3 interpersonal circumplex |
| | Rahim, *A measure of styles of handling interpersonal conflict*, Academy of Management Journal 26(2), 368–376, 1983. doi:10.2307/255985 | 7.4 five conflict styles |
| | Lazarus and Folkman, *Stress, Appraisal, and Coping*, Springer, 1984 | 7.5 stress and coping. Book; no Crossref record found, details **only from other papers' reference lists** |
| D8 Current focus | Little, *Personal projects: A rationale and method for investigation*, Environment and Behavior 15(3), 273–309, 1983. doi:10.1177/0013916583153002 | 8.1–8.2 personal projects |
| | Emmons, *Personal strivings: An approach to personality and subjective well-being*, Journal of Personality and Social Psychology 51(5), 1058–1068, 1986. doi:10.1037/0022-3514.51.5.1058 | 8.3 recurring goals and concerns |
| D9 Life and preferences | none | Jiang et al., *Know Me, Respond to Me* (PersonaMem), COLM 2025, arXiv:2504.14225, shows preferences are the target of LLM personalization benchmarks; that is practice, not a psychological construct |

**Gaps this mapping exposes**

- No dimension holds broad traits (McAdams level 1). Big Five is measured only in the survey
  eval with Mini-IPIP: Donnellan, Oswald, Baird and Lucas, *The Mini-IPIP scales: Tiny-yet-effective
  measures of the Big Five factors of personality*, Psychological Assessment 18(2), 192–203, 2006.
  doi:10.1037/1040-3590.18.2.192.
- D5 and D9 come from personalization practice, not personality research.
- Facets with no counterpart in the papers above: 1.1, 1.4, 2.2–2.4, 3.4–3.5, 4.3; 4.1–4.2 only
  tangentially (need for cognition).
- Facets were not derived from any instrument; nothing tests whether 39 facets are distinct or
  complete, and no ablation shows that a dimension improves answers.

**Alternative taxonomies for the ablation** (checked against Crossref / the publisher landing page)

- Soto and John, *The next Big Five Inventory (BFI-2): Developing and assessing a hierarchical model
  with 15 facets to enhance bandwidth, fidelity, and predictive power*, Journal of Personality and
  Social Psychology 113(1), 117–143, 2017. doi:10.1037/pspp0000096.
- Schwartz, *An overview of the Schwartz theory of basic values*, Online Readings in Psychology and
  Culture 2(1), 2012. doi:10.9707/2307-0919.1116. Ten basic values.

## F. Prior art for the taxonomy and its mechanisms (searched 2026-10-19)

Full comparison, per-work categories and verdicts in [TAXONOMY_RESEARCH.md](TAXONOMY_RESEARCH.md)
(Chinese). How each was checked: **[PDF]** relevant sections of the paper read; **[HTML]** arXiv HTML
sections read through a fetch tool (category names may be paraphrased; check the paper before
quoting); **[abstract]** abstract page only; **[code]** repository source read. Venue is from the
ACL Anthology / publisher page unless marked "per arXiv comment" (only the authors' note checked).

**Closest taxonomies (content of a person)**

- Wang (Zhen) et al., *DeepPersona: A Generative Engine for Scaling Deep Synthetic Personas*,
  arXiv:2511.07338, 2025. [HTML], appendix table not read; NeurIPS 2025 track unverified. 12
  top-level attribute classes, 8,496-node tree; closest content match, used to synthesize personas.
- Zhou (Jinfeng) et al., *CharacterGLM: Customizing Chinese Conversational AI Characters with Large
  Language Models*, arXiv:2311.16832, 2023. [HTML]; later venue unverified. Attributes + behaviours;
  the role-play field list closest to twin.
- Chen (Chaoran) et al., *Towards a Design Guideline for RPA Evaluation: A Survey of Large Language
  Model-Based Role-Playing Agents*, Findings of ACL 2025. [HTML]. Six agent attributes from 1,676
  papers.
- Chen (Jiangjie) et al., *From Persona to Personalization: A Survey on Role-Playing Language
  Agents*, TMLR 2024, arXiv:2404.18231. [PDF] §2–3, §6.1; §7 not read. Fidelity layers; names
  digital clones and persona drift as open problems.
- Gao (Silin) et al., *PeaCoK: Persona Commonsense Knowledge for Consistent and Engaging
  Narratives*, ACL 2023. [PDF] §3–4.1. Five relations plus per-fact temporal labels.
- Kang (Jiazheng), Ji, Zhao, Bai, *Memory OS of AI Agent*, EMNLP 2025, arXiv:2506.06326. [HTML],
  [code]. "90" user-trait dimensions (about 51 counted in the released prompt; to recount).
- Jiang (Bowen) et al., *PersonaMem-v2: Towards Personalized Intelligence via Learning Implicit
  User Personas and Agentic Memory*, arXiv:2512.06688, 2025. [HTML].
- Wu (Di) et al., LongMemEval (section B), appendix A.1: 164 user attributes in 5 classes. [HTML].
- Park et al., arXiv:2411.10109 (section "Read"): the American Voices Project's 12 interview
  domains (Stanford Center on Poverty and Inequality methodology page, fetched) and SM Table 7. [PDF].
  The authors chose a protocol independent of their evaluation; twin's taxonomy is not.
- Wei et al., Second Me (section "Read"): L0/L1/L2; "shades" are clustered interest domains with
  memory-id timelines and five confidence levels, found only in code. [PDF], [code]
  `mindverse/Second-Me` `lpm_kernel/L1` at d0e4025.
- Toubia et al., Twin-2K-500 (section A), arXiv:2505.17479; Marketing Science doi
  10.1287/mksc.2025.0262 from search results, publisher page not opened. [PDF] Table 1.
- McAdams, *The Life Story Interview – II*, Foley Center, Northwestern University, revised 2007.
  [PDF], full text.

**Role-play evaluation dimensions** (evaluation axes, not memory organisation): CharacterEval (Tu et
al., ACL 2024), RoleLLM (Wang et al., Findings of ACL 2024), Character-LLM (Shao et al., EMNLP 2023
per arXiv comment), CharacterBench (Zhou et al., AAAI 2025 per arXiv comment), InCharacter (Wang et
al., ACL 2024), PersonaGym (Samuel et al., Findings of EMNLP 2025), TimeChara (Ahn et al., Findings
of ACL 2024 per arXiv comment), TwinVoice (Du et al., arXiv:2510.25536; ACL 2026 Findings from search
results, unverified). All [HTML].

**Memory frameworks** (classify by memory form, not content): MIRIX (Wang and Chen,
arXiv:2507.07957), MemGPT (Packer et al., arXiv:2310.08560), CoALA (Sumers et al., TMLR,
arXiv:2309.02427), Zep (Rasmussen et al., arXiv:2501.13956; [PDF] §2), Mem0 (section B; [HTML] §2).

**Mechanisms**

- Menick et al., *Teaching language models to support answers with verified quotes* (GopherCite),
  arXiv:2203.11147, 2022. [PDF] §2.
- An, *Fidelity Before Structure: Verbatim Chunks Beat Lossy Artifact Extraction in
  Long-Conversation LLM Memory*, arXiv:2601.00821 (v4 2026-07). [abstract]; appendix prompts searched.
- Wu and Zhu, *Agent Zero Memory: Provenance-Aware Long-Term Memory for LLM Agents*,
  arXiv:2608.29606, 2026. [abstract].
- DeLucia et al., *Using Natural Language Inference to Improve Persona Extraction from Dialogue in a
  New Domain*, arXiv:2401.06742, 2024. [abstract].
- Yang (Lu), Xu, Li, Yang, Huang, *When Personal Memory Has No Single Answer: Evaluating LLM Agents
  under Irreducible Conflict* (TANGLE), arXiv:2608.13921, 2026. [HTML] body, [PDF] appendices A, B, K
  (see [CONFLICT_EVAL.md § 2.1](CONFLICT_EVAL.md)). Keeps irreducible conflicts instead of forcing
  one answer, so "keep the contradiction" is not ours to claim. Its source contradictions are all
  record-type facts; it does not test said-versus-done and has no gold answer.
- Peng, Gui, Brucks, Merlau et al., *Digital Twins as Funhouse Mirrors*, arXiv:2509.19088, 2025.
  [abstract]. Motivation for abstaining instead of filling gaps with stereotypes.
- Behaviour versus self-report, details checked against Crossref (not read):
  Samuelson, *A note on the pure theory of consumer's behaviour*, Economica 5(17), 61–71, 1938,
  doi:10.2307/2548836;
  LaPiere, *Attitudes vs. actions*, Social Forces 13(2), 230–237, 1934, doi:10.2307/2570339;
  Nisbett and Wilson, *Telling more than we can know: Verbal reports on mental processes*,
  Psychological Review 84(3), 231–259, 1977, doi:10.1037/0033-295X.84.3.231;
  Fleeson, *Toward a structure- and process-integrated view of personality: Traits as density
  distributions of states*, Journal of Personality and Social Psychology 80(6), 1011–1027, 2001,
  doi:10.1037/0022-3514.80.6.1011.

## To search for once network access is available

- Follow-ups citing Park et al. 2024/2025 (individual simulation, digital twins, survey prediction).
- Chinese-language or non-U.S. replications of individual simulation.
- Twins evaluated against later behaviour rather than self-report (our proposed direction).
- Work on fabricated quotations or misattribution in persona simulation.
- Before submission: re-run the prior-art search for taxonomies and evidence-bound persona memory
  (TANGLE and Agent Zero Memory appeared in August 2026); commercial twin products (Delphi,
  Personal.ai) published no method documents we could find; Chinese-language venues not searched.
