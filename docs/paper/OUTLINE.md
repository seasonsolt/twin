# Paper outline: Grounded, Not Trained

Working draft. Numbers marked **[have]** come from runs already documented in
[COMPARISON.md](../COMPARISON.md); numbers marked **[todo]** need new runs before submission.
The summary of Second Me (arXiv:2503.08102) below is from memory and must be checked
against the paper before any sentence about it is written.

---

## Title options

1. **Grounded, Not Trained: Evidence-Bound Memory for Personal Digital Twins**
2. Can Parametric Memory Be a Second Me? Evidence, Abstention and Forgetting in Personal AI Twins
3. Every Claim Has a Quote: Evidence-Bound Personal Twins without Fine-Tuning

## One-sentence thesis

A personal digital twin should take its facts about the person from retrieved, verbatim,
dated evidence and refuse when there is none. Training the person into model weights cannot
provide provenance, calibrated abstention or reliable forgetting, and upgrading the
components does not change that.

## Abstract (draft, ~200 words)

> Personal digital twins answer as a specific person would. A prominent line of work, exemplified
> by Second Me, encodes the person into a fine-tuned model ("AI-native" parametric memory) trained
> on data synthesized from their documents. We argue that this design cannot meet three
> requirements a twin must meet to be trusted: answers traceable to what the person actually said,
> refusal when the person never addressed a question, and reliable removal of withdrawn material.
> We first upgrade every replaceable component of Second Me to current best choices and show
> that the gaps remain: fabrication on unanswerable questions, style that does not resemble the
> person, and deletions that do not take effect. We then present twin, an evidence-bound
> alternative with no fine-tuning. Two-layer memory stores the person's verbatim expressions and
> a persona profile of 39 facets in which every claim carries verbatim-verified, dated quotes.
> A three-mode answering contract (grounded, general, abstain) is enforced by model-independent
> checks, including a quote guard that removes quotation marks from spans not found in the
> material. Incremental, content-addressed rebuilds make deletion exact and support answering
> "as of" any date. On [N] subjects with a factorial control for the answering model, twin
> [todo: headline result]. We release the evaluation protocol, including a quote-provenance
> metric for personal twins.

---

## 1. Introduction

- Motivation: twins of real people are being deployed (assistants, executives' proxies,
  memorial bots). Being wrong about a real person is a different kind of harm from being wrong
  about the world. It puts words in their mouth.
- Three requirements, stated as testable properties:
  - **R1 Provenance.** Each factual claim about the person is backed by something they said,
    with date and source.
  - **R2 Abstention.** If the person never addressed a question, the twin says so instead of
    inventing a position.
  - **R3 Forgetting.** Removing material removes everything derived from it, without retraining.
- Claim: parametric memory violates R1 to R3 by construction; retrieval alone is not enough
  either (agent-memory frameworks remember facts *about* a user, not who the user is).
- Contributions (numbered list, mirrors sections 3 to 6):
  1. A component-upgrade ablation of Second Me that isolates architecture from modules.
  2. twin: evidence-bound two-layer memory, three-mode contract, model-independent checks.
  3. Deterministic incremental rebuild giving exact deletion and `as_of` answering.
  4. An evaluation protocol for personal twins, including a quote-provenance metric and
     controlled add/modify/delete, released with synthetic personas.

## 2. Background and related work

- **Parametric personal memory.** Second Me (L0 raw data, L1 natural-language memory,
  L2 LoRA-trained model; SFT/DPO on synthetic data). WeClone (style LoRA from chat logs).
  Character/role-play fine-tuning.
- **Profile-in-prompt twins.** Distilly (one-shot persona and skill document, no retrieval).
- **Agent memory.** mem0, Letta/MemGPT, Graphiti/Zep (temporal KG), MemOS, Cognee, MIRIX.
  Benchmarks LoCoMo, LongMemEval measure recall of conversations, not fidelity to a person.
- **Faithfulness and attribution.** RAG attribution, citation evaluation, selective prediction
  and abstention in QA.
- **Machine unlearning.** Why deletion from fine-tuned weights is hard; contrast with
  deletion by recomputation.
- **Digital humans.** Duix/HeyGem, LiveTalking, Fay: appearance and voice without
  identity-level memory. (Only cited to scope the paper; media is out of scope.)

## 3. Does parametric memory fall short because of components or architecture?

The upgrade ablation, already run on the author's own data **[have]**.

- Setup: fork of Second Me (seasonsolt/Second-Me). Replace every module without changing the
  architecture: Qwen2.5-0.5B → Qwen3-1.7B, MLX LoRA on Apple Silicon, retrieval memory (facts
  from retrieval, LoRA for style only), 1024 → 8192 context, per-embedding-model retrieval
  thresholds.
- Same 59-question set, same judge script (`judge.py`), judge `gpt-6.1-sol`.

| Metric | Original (0.5B) | Upgraded (1.7B) |
| --- | --- | --- |
| Fact accuracy (32) | 4.7% | 78.1% |
| No fabrication (10) | 10% | 70% (best run 80%) |
| Style (1–5, 10) | 1.0 | 1.9–2.2 |
| General quality (1–5, 5) | 2.2 | 3.0–3.2 |
| Memory update (6 pts) | 0 | 3.5 (delete 0/2) |

- Diagnosis: three gaps remain and each traces to the architecture:
  - no verbatim evidence, so no provenance (R1);
  - confidence is self-reported, so no principled abstention (R2);
  - synthetic training data is derived from memory, so weights do not follow edits (R3).
- Also report the robustness failures found while upgrading (e.g. single-shade profile
  producing empty bios and invalid training data while the UI reports success). Keep this short
  and factual.
- **[todo]** Re-run with a cross-family judge panel and more questions so section 3 does not
  rest on one judge and one subject.

## 4. twin: evidence-bound memory

Figure 1: pipeline from sources to expressions, candidates, persona items and index
(adapt the mermaid diagram in [ARCHITECTURE.md](../ARCHITECTURE.md)).

### 4.1 Layer 1: expressions
- Source parsing keeps only the subject's own words; other people are pseudonymized before any
  model, vector store or chat sees them.
- Each expression carries date, channel, context (preceding question/messages) and whether it
  is first-person or third-party report.
- Audio/video: transcription, diarization, identifying the subject's voice.

### 4.2 Layer 2: persona items
- Taxonomy: 9 dimensions, 39 facets ([PERSONA_DIMENSIONS.md](../PERSONA_DIMENSIONS.md)).
  Justify the taxonomy briefly (identity, values, decision style, thinking, expertise, speech,
  relationships, current focus, life; life facets gated on consent).
- Extraction in 6000-character segments: each candidate must cite 1–3 spans that pass
  verbatim verification, otherwise it is dropped.
- Per-facet merge: synonyms merged, **behavioural evidence outranks self-report**,
  contradictions kept and flagged as conflicts rather than resolved for the person.
- Support counted as distinct (source × date) pairs.
- Owner review: confirm, edit or reject each item; decisions survive re-merges.

### 4.3 Incremental, content-addressed rebuild
- Segment, candidate and item IDs are content hashes. New material extracts only unseen
  segments; only facets whose candidate set changed are re-merged; output is a per-facet diff.
- Deletion recomputes everything depending on the removed source. State the property:
  *after deleting source s, no persona item cites s and no expression from s is retrievable.*
  Back it with the test suite.
- `as_of`: every piece of evidence is dated, so filtering evidence by date answers
  "what would they have said on day d".

## 5. Answering contract

### 5.1 Context assembly
- Hybrid retrieval (dense + BM25, reciprocal rank fusion k=60): 12 persona items, 6 expressions.
- Core profile: top 2 items per dimension by support, always present.
- Speech samples: 8 most recent first-person chat expressions.
- Last 8 conversation turns.

### 5.2 Three modes
| Mode | When | Confidence cap |
| --- | --- | --- |
| grounded | about the person and the material covers it | 0.6 if it cites only unconfirmed third-party reports |
| general | not about the person | 0.5, and prefaced as not the person's view |
| abstain | about the person but not covered, or committing on their behalf, or judging a named third party | 0.3 |

- Note the prompt-ordering finding: checking "is this about the person?" first, then
  "is this a commitment on their behalf?", then defaulting to general, stopped a fast model from
  over-abstaining on general questions (5/15 → 0) **[have]**.

### 5.3 Model-independent checks
- **Citation check.** Only IDs actually in this turn's context survive.
- **Confidence caps.** Applied after the model, regardless of what it reports.
- **Quote guard.** Spans in quotation marks are normalized (NFKC, whitespace/punctuation
  stripped, lowercase Latin) and searched in the material the model saw (raw and
  pseudonymized). Spans not found lose their quotation marks; the text stays.
  - Evidence that this is needed: frontier models still fabricate quotes from the person.
    26 spans stripped at runtime with `gpt-5.6-sol`, 49 with `deepseek-flash`, 0 surviving
    in final answers **[have]**.

## 6. Evaluation protocol

Released as a reusable harness (`src/twin/evals/`, [PERSONAL_EVAL.md](../PERSONAL_EVAL.md)).

- **Categories.** fact (with gold answer, evidence, source), unanswerable, style
  (persona + quality, separate judge calls), general, update (add → modify → delete on a
  private DB copy, scored at each step; delete scored as abstention).
- **Statistics.** Repeated answers; judge panel with `all_judges_required`; per-question
  averaging so repeats and judges are not counted as independent units; bootstrap CIs that
  resample **source groups** (fact by document, update by original item), 2000 resamples,
  deterministic seed; paired B − A comparison with win/loss/tie counts.
- **Quote-provenance metric** (no judge needed). Each quoted span classified as
  *cited* (in material the answer cites), *elsewhere* (in the subject's material but not cited),
  *question* (echoes the prompt) or *unverified*. Argue why citation-ID validity is not enough:
  a valid ID does not prove the quoted words are the person's.
- **Privacy by design.** Question sets and materials stay outside the repository; outputs are
  0700/0600; records redact endpoints and secrets. Matters for any study with real people.

## 7. Experiments

### 7.1 Subjects and data
- **[have]** S1: the author, 59 questions.
- **[todo]** S2–S10: consenting volunteers with real material (notes, chats, documents,
  recordings). Ethics/consent procedure, compensation, withdrawal = run deletion.
- **[todo]** Synthetic personas (generated life histories with planted facts, planted gaps and
  planted contradictions) so the benchmark can be released.
- **[todo]** Target at least 50 questions per category per subject; update at least 20 items.

### 7.2 Systems
| System | Memory | Answerer |
| --- | --- | --- |
| Second Me original | LoRA + bio/shades | Qwen2.5-0.5B |
| Second Me upgraded | retrieval + style LoRA | Qwen3-1.7B |
| Distilly | one persona document in prompt | same as twin |
| mem0 (or Letta) **[todo]** | extracted user facts | same as twin |
| twin | evidence-bound two-layer | frontier / fast / small |

### 7.3 Main experiment: architecture × answering model (2×2) **[todo, required]**
The current comparison confounds architecture with model size. Run:

| | Small model (Qwen3-1.7B, local) | Frontier model |
| --- | --- | --- |
| Second Me architecture | have | **todo**: Second Me retrieval + prompt on frontier model |
| twin architecture | **todo**: twin with `[chat_llm]` = Qwen3-1.7B | have |

The paper's argument holds if the architecture effect survives within each column, especially
abstention and deletion. If twin on 1.7B loses on facts but keeps abstention and deletion,
that is still the central claim and should be reported as such.

### 7.4 Results to report
- Table 1: main results, all systems × all categories, with source-group CIs.
- Table 2: the 2×2 with interaction.
- Figure 2: fabrication vs helpfulness (unanswerable abstain rate vs general-question
  abstain rate) per system. This shows the cost of abstention honestly.
- Figure 3: quote-provenance breakdown per system (cited / elsewhere / question / unverified),
  before and after the quote guard.
- Table 3: update results, with deletion success counted per item.
- `as_of` experiment **[todo]**: questions whose answer changed over time; accuracy for
  answers dated before and after the change.

### 7.5 Ablations **[todo]**
- Without verbatim verification at extraction.
- Without the persona layer (expressions only, plain RAG).
- Without the expression layer (persona items only).
- Without core profile / speech samples (effect on style).
- Without behaviour-over-self-report merge (effect on contradiction questions).
- Without quote guard (unverified quote rate rises; facts unchanged?).
- Without confidence caps (calibration: ECE or AURC on fact + unanswerable).
- Few-shot style examples (already observed: style fell to 3.8 **[have]**).

### 7.6 Human evaluation **[todo]**
- Style judged by people who know each subject: blind A/B between systems, plus
  "could this have been them?" rating.
- Subject self-rating: would you sign this answer? Does it put words in your mouth?
- Report agreement between humans and the LLM judge panel.

### 7.7 Cost and latency
- **[have]** first token / full answer: `deepseek-flash` about 0.7 s / 2 s,
  `gpt-5.6-sol` about 3.7 s / 5 s.
- **[todo]** build cost per 100k characters of material; incremental update cost vs a
  Second Me retraining run.

## 8. Discussion

- Where fine-tuning still helps: style. Distilly beat twin on blind style comparisons in early
  synthetic tests (12 wins to 11 **[have]**). Position fine-tuning as an optional style rewriter
  that may only change wording, is re-checked for citations, and is enabled only if it wins on
  evaluation.
- Abstention vs helpfulness: what the twin refuses, and why that is the right default for a
  real person.
- Behaviour vs self-report: twins should show how someone acts, not only how they describe
  themselves; conflicts belong to the person to resolve.
- Deployment observations (brief): multiple twins per user, workplace chat, owner review of
  items. No product claims.

## 9. Limitations

- Results so far: one subject, small categories (10 / 10 / 5 / 2), judge in the same family as
  one answerer. All addressed in section 7 or stated plainly if not.
- Depends on external LLMs for extraction; extraction errors that pass verbatim verification
  can still misinterpret a quote.
- The taxonomy is the authors' design; no validation against psychometric instruments.
- Chinese-language material dominates; cross-language results unknown.

## 10. Ethics

- Consent: twins only of consenting people; face and voice only with the person's consent.
- Third parties: pseudonymized before leaving local storage; judgements about named others
  are never stored or answered.
- Data handling: per-twin storage, disclosure of every external service data goes to.
- Misuse: impersonation risk; abstention and visible evidence reduce but do not remove it.
- Right to be forgotten: deletion as recomputation, verified by the update evaluation.

## 11. Conclusion

Twins of real people should be held to evidence, not fluency. Provenance, abstention and
forgetting are architectural properties; build them in rather than training around them.

---

## Appendices

- A. Full 39-facet taxonomy with definitions.
- B. Prompts: extraction, merge, chat (with mode-ordering variants).
- C. Judge rubrics (version 1) and judge panel configuration.
- D. Quote-normalization rules and the classifier for quote provenance.
- E. Second Me upgrade details and failure cases.
- F. Synthetic persona generator and release format.
- G. Consent form and data-handling protocol for volunteer subjects.

## Release

- Code: twin (already public), evaluation harness, synthetic personas and question sets.
- Not released: any real subject's material, question sets or records.

## Work plan before submission

1. Check every statement about Second Me against arXiv:2503.08102 and its code.
2. Build the synthetic persona generator and question sets (enables release and scale).
3. Run the 2×2 (section 7.3). This is what reviewers will ask for first.
4. Add a cross-family judge panel to the harness; re-run S1.
5. Recruit volunteers; run all systems; collect human style ratings.
6. Ablations (7.5) on synthetic personas first, then a subset of real subjects.
7. Write; post to arXiv as a technical report; then submit to an ACL/EMNLP-family venue
   (or FAccT/CHI if the paper leans on consent, forgetting and provenance).
