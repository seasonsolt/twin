# Reading notes: Park et al., arXiv:2411.10109v3

*LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals*
(Park, Zou, Kamphorst, Egan, Shaw, Hill, Cai, Morris, Liang, Willer, Bernstein). Page numbers are
main text (p.) and supplementary materials (SM p.).

## What they did

- **Sample.** 1,052 U.S. adults, stratified by age, gender, race, region, education, party (Bovitz).
  Paid $60 + $30, plus a $0–10 bonus from the economic games. IRB process of over six months; withdrawal
  honoured for 25 years (SM p.3–4).
- **Data.** Wave 1: a ~2-hour voice interview by an AI interviewer (American Voices Project script,
  99 scripted questions, ~82 generated follow-ups, ~6,491 words from the participant), then GSS core
  (177 categorical + 6 numerical), BFI-44, five economic games, five experiments. Wave 2 (~2 weeks
  later): everything except the interview (SM p.3, p.8–9).
- **Interviewer.** Scripted question verbatim, then an LLM decides "follow up or move on" within a time
  budget per question. A reflection module keeps bullet-point notes so the prompt holds notes plus the
  last 5,000 characters, not the whole transcript (SM p.5–9). Script in SM Table 7 (p.61–65).
- **Agents (GPT-4o).** Three self-report agents: interview-only, survey-only (GSS + BFI-44), and
  survey + interview. Two baselines: demographic sentence (Argyle-style) and a self-written persona
  paragraph (SM p.22). Whole source injected into the prompt, no retrieval. "Expert reflection":
  psychologist, behavioural economist, political scientist and demographer each write 5–20
  observations once; at answer time the model picks one expert and appends their notes (SM p.11–12).
- **Prediction prompt.** Forced choice with chain of thought: interpret each option → reason per option
  → overall reasoning → response (SM p.13).
- **Leakage control.** Survey agents never see the item being predicted (GSS) or its whole trait block
  (BFI). 54,694 GSS × interview question pairs screened by a GPT-4.1 classifier plus human review; 27 GSS
  items removed, leaving 150 evaluation items (p.12, SM p.26–30). Including them adds only +0.02.

## Metrics

- **Normalized accuracy** = agent accuracy ÷ participant's own wave-1/wave-2 agreement, per person,
  then averaged across people (SM p.18). Note: Figure 1's caption says agents are compared with
  wave-2 answers, while SM p.18 says wave 1; the SM is the detailed account.
- Categorical items: exact match. Correlations: categorical options one-hot encoded with weights
  summing to one item; ordinal options spaced evenly on 0–1. BFI and games: trait or game scores,
  Pearson r averaged with Fisher z; MAE in the SM (SM p.19–20).
- Bias: demographic parity difference (best minus worst subgroup).

## Results worth remembering

| | GSS accuracy | GSS normalized | BFI normalized r | Games normalized r |
| --- | --- | --- | --- | --- |
| Participants (retest) | 79.53% | 1.00 | 1.00 | 1.00 |
| Survey + interview | 68.30% | 0.86 | 0.77 | 0.49 |
| Interview | 65.67% | 0.83 | 0.80 | 0.66 |
| Survey | 64.98% | 0.82 | 0.65 | 0.38 |
| Demographic | 58.12% | 0.74 | 0.61 | 0.47 |
| Persona paragraph | 56.21% | 0.71 | 0.75 | 0.57 |
| Chance | ~30% | | | |

(SM Table 8, p.66.)

- **Economic games are a boundary case:** no agent type differs significantly from another
  (F = 1.63, p = 0.16); construct-level correlations are near zero (dictator 0.11, public goods −0.05)
  (p.7, SM p.40, p.45).
- **Content, not wording:** removing 80% of the interview → 0.79; bullet summary → 0.81 (p.8, SM Table 6).
- **Why interviews work (SM §8):** "direct retrieval" of answers stated in the transcript, and
  "inference" from other facts. Both matter; removing the 30 most retrievable and 30 most inferable
  items still leaves interview agents 0.080 ahead of demographic agents, so other mechanisms remain.
- **Models (SM §9):** GPT-5 / 4.1 / o1 / o3 ≈ 0.67 raw vs GPT-4o 0.66; mini models 0.60–0.64; drift over
  a year −0.02.
- **Fine-tuning does not help (SM §9):** GPT-4o fine-tuned on 500 agents' GSS answers reached 0.79
  normalized on the other 552, vs 0.84 for the prompted agent with reasoning and reflection.
- **Item-level:** demographic and household facts are near ceiling; trust/fairness/helpfulness items
  ~0.42–0.47 raw; wealth stereotypes (wlthwhts etc.) are the worst (SM p.41–44).
- Stated limitations: individual accuracy only (no inter-item correlation structure), five experiments
  underpowered, one model family, English and U.S. only (p.10–11).

## What this means for twin

1. **Adopt:** normalized accuracy against the person's own retest (done in `twin survey`), leakage
   screening between memory and evaluation items, persona-paragraph and demographic baselines, and the
   lesion and summary ablations.
2. **Supports our thesis:** fine-tuning lost to prompting (0.79 vs 0.84), and content matters more than
   wording, which favours twin's evidence layers over LoRA style training.
3. **Open tension:** their agents gain from *inference* beyond what is stated; twin abstains when the
   material does not cover a question. `--force-choice` vs the default measures exactly how much
   accuracy abstention costs and how much calibration it buys. This is a result in itself.
4. **Gaps they leave:** non-English and non-U.S. people, time (no `as_of`, no update), provenance,
   behaviour beyond self-report (the games failed), and populations of one (a single person's twin
   over a long, growing record rather than a 2-hour snapshot).
5. **Instrument choices for a consumer product:** the games add little signal per item; single
   personality items cannot give trait scores. Use a public-domain multi-item personality scale
   (IPIP, e.g. the 20-item Mini-IPIP) instead of BFI-44, and check licences before reusing
   CGSS/WVS items in a commercial product.
