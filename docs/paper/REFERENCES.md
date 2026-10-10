# Reading list

Compiled without network access, from memory. **Check every title, venue and arXiv number before
citing.** Only the two papers marked "read" have been checked against the PDF.

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

## To search for once network access is available

- Follow-ups citing Park et al. 2024/2025 (individual simulation, digital twins, survey prediction).
- Chinese-language or non-U.S. replications of individual simulation.
- Twins evaluated against later behaviour rather than self-report (our proposed direction).
- Work on fabricated quotations or misattribution in persona simulation.
