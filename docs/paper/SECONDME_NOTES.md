# Reading notes: Wei et al., arXiv:2503.08102v2

*AI-native Memory 2.0: Second Me* (Jiale Wei, Xiang Ying, Tao Gao, Fangyi Bao, Felix Tao, Jingbo Shang;
Mindverse.ai). 14 pages, "Preprint. Under review." Page numbers refer to the PDF.

## What it claims

- **Architecture (p.2–3).** Keeps the three layers of their earlier Large Personal Model (LPM 1.0,
  Shang et al. 2024, arXiv:2406.18312): L0 raw data (RAG over everything), L1 natural-language memory
  (bio, key sentences, preference tags), L2 "AI-native memory" held in model parameters. New in 2.0:
  L0/L1 feed L2 as context; L2 becomes an orchestrator that calls expert models, tools and the internet
  ("context provider", not task executor); a fully automated training pipeline.
- **Pipeline (p.4–5, Fig. 2).** Raw data → cleaning → GraphRAG-style mining of entities, topics, a
  global biography → synthetic QA and context data from GPT/DeepSeek → five-level filtering → PEFT
  (LoRA) SFT on **Qwen2.5-7B-Instruct** → DPO on sampled pairs (~20% of the SFT volume) → automatic
  evaluation.
- **Tasks (p.4).** Memory QA (Self: answering the user; Third-party: representing the user to others),
  Context Enhance (rewrite a user's request for an expert model with details from memory), Context
  Critic (critique an expert's answer on the user's behalf).
- **Findings (Tables 1–2, p.5–7).** "Strong" chain-of-thought data (DeepSeek-R1 with format and length
  constraints) beats weak and multi-step CoT; DPO helps. Best: Memory Self 0.96, Third-party 0.76,
  Enhance 0.85, Critic 0.86 (ratios of full score).

## How it was evaluated (Appendix B–C, p.12–13)

- **One user**: an internal staff member, 132 notes and 62 todos, ~7k synthetic instruction pairs.
- **Test set synthesized by the same pipeline** as training data (question generation + the same CoT
  synthesis + filtering), "isolated" from the training set but drawn from the same generator: 60 Self +
  60 Third-party Memory QA, 60 Enhance, 60 Critic.
- **LLM-as-judge**, model unnamed. Memory QA rubric: Correctness = "must **not conflict** with recorded
  content", Helpfulness, Completeness, Empathy (Role-correctness for third-party), each 0 / 0.5 / 1.
- "Human evaluation" is mentioned (Strong CoT ≈ 0.95, with DPO ≈ 1) without raters, numbers of items or
  protocol (p.6).

## Weaknesses that matter for our paper

1. **No test of fabrication.** Correctness only penalizes *conflict* with records, not claims the
   records do not support. There is no unanswerable category. The paper itself notes that Strong CoT
   outputs "include reasonable but unreferenced content" (p.6), and the Fig. 3 example answer
   ("quantum glows… Weiming Lake… a collapsing and reconstructing stargate") shows how far free
   elaboration goes. This is the gap our 10% non-fabrication result measures.
2. **Circular, synthetic evaluation.** Questions come from the same synthesis pipeline as the training
   data; no held-out human questions, no baselines (no RAG, no long context, no prompted frontier model)
   in this paper. The LPM 1.0 claim of beating RAG is not re-tested.
3. **n = 1, no intervals,** unnamed judge; the authors acknowledge length bias toward Completeness and
   Empathy (p.7) and say evaluation code is being corrected (p.7).
4. **No updates or deletion.** Nothing on what happens when memories change; retraining is implied.
5. **No provenance** for any answer.
6. **Unsupported application claims** (p.8): network efficiency "by 3 to 5 orders of magnitude"
   (Metcalfe's law), NFT-based cognitive assets.

## Corrections to what we wrote from memory

- The base model in the paper is **Qwen2.5-7B-Instruct**. Our comparison ran the open-source default
  (Qwen2.5-0.5B) and our upgraded fork (Qwen3-1.7B). **A reviewer will ask for the 7B configuration**;
  add it to the comparison, or state clearly that we tested the released default.
- The judge model is not named in the paper; do not say GPT-4o.
- Training is PEFT/LoRA SFT + DPO on synthetic data, as we described.

## Contrast with Park et al. (see PARK_NOTES.md)

| | Second Me | Park et al. |
| --- | --- | --- |
| Ground truth | LLM judge of synthetic questions | The person's own answers, twice |
| Subjects | 1 internal staff member | 1,052 stratified adults |
| Baselines | None in this paper | Demographic, persona paragraph |
| Fine-tuning | Central | Tested and did not help (0.79 vs 0.84) |
| Ceiling | None | Person's two-week test–retest |

Park et al.'s fine-tuning result and their retest-normalized protocol are the strongest external
evidence for our argument; Second Me's own evaluation design explains why its weaknesses did not show
up in its reported numbers.
