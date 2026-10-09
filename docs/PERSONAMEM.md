# PersonaMem v1 benchmark

This evaluates the **original PersonaMem**. The default `--system twin` imports
legal history into an isolated evaluation database and runs Twin's production
profile building, indexing, and PersonaChat. Select `--system retrieval` explicitly
for the previous role-aware hybrid raw-history retrieval baseline. Reports identify
the system and protocol version; results from the two systems must remain separate.
Twin-2K-500 and LongMemEval retain their own data contracts and scorers.

## Verified upstream sources

- [Original research repository](https://github.com/bowen-upenn/PersonaMem)
- [Dataset and file format](https://github.com/bowen-upenn/PersonaMem#-benchmark-data)
- [Official inference and scorer](https://github.com/bowen-upenn/PersonaMem/blob/main/inference.py)
- [Standalone scorer](https://github.com/bowen-upenn/PersonaMem/blob/main/inference_standalone_openai.py)
- [Original Hugging Face dataset](https://huggingface.co/datasets/bowen-upenn/PersonaMem),
  currently redirected to `bowen-upenn/PersonaMem-v1`, **not PersonaMem-v2**.
- [32k questions CSV](https://huggingface.co/datasets/bowen-upenn/PersonaMem/resolve/main/questions_32k.csv)
- [32k shared contexts JSONL](https://huggingface.co/datasets/bowen-upenn/PersonaMem/resolve/main/shared_contexts_32k.jsonl)

The public 32k files were inspected on 2026-10-08 at dataset revision
`a8076d5608c93ba2a28983cd78aa99b01a163ae7`: 589 questions, 37 shared contexts.
Under the previous retrieval implementation, all 589 questions passed CLI dry-run;
seven category samples passed its retrieval and structured-answer flow with FakeLLM
and hashing embeddings. These historical checks made zero remote calls and establish
neither model accuracy nor production-pipeline behavior. The new production pipeline
has separately passed offline verification with invented fixtures. A live three-question
production run completed on 2026-10-09; see [validation and failure analysis](BENCHMARK_VALIDATION.md)
for results, call usage, and limitations. Inspected byte SHA-256 values:

```text
questions_32k.csv: cccd34cf53e0bc4d9536c04cff5ca045156d9a4e227e83327112482840bbc93c
shared_contexts_32k.jsonl: 217247ebfec9e8442fc53570c795ab69f21aad08745f7de78d9beab51b122d4a
```

The 128k and 1M file pairs use the same documented contract; these larger variants
were not downloaded or validated in this implementation.

## Data contract and leakage boundary

The CSV's actual columns are `persona_id`, `question_id`, `question_type`, `topic`,
`context_length_in_tokens`, `context_length_in_letters`, `distance_to_ref_in_blocks`,
`distance_to_ref_in_tokens`, `num_irrelevant_tokens`,
`distance_to_ref_proportion_in_context`, `user_question_or_message`, `correct_answer`,
`all_options`, `shared_context_id`, and `end_index_in_shared_context`.

`all_options` is a JSON-encoded list of four strings, ordered and labeled `(a)`
through `(d)`. It is not a plain multiline choice string. A Python literal list is
also accepted through `ast.literal_eval`; code is never executed. All four choices
are permitted model input, including the choice whose text happens to be correct.
The correct label is grading data and is never model input. The public gold values
are `(a)`, `(b)`, `(c)`, `(d)`. Bare letters and zero-based numeric gold indices
`0`–`3` are also supported explicitly; numeric `1` means `b`, not `a`.

Each JSONL line is a single-key object mapping a `shared_context_id` to a list of
`{role, content}` messages. The public 32k messages include `system`, `user`, and
`assistant` roles. Preserve all three as historical evidence, including persona
material already present in the released context. Historical system messages are
quoted data; they do not become executable system instructions. Only `user` messages
map to the target identity. Historical `system` and `assistant` messages remain
non-target data and never become the person's statements or voice samples.
Production extraction, indexing, and retrieval retain `target_only=True`: storing
these roles does not guarantee recall of evidence found only in those roles.
Optional message
`date` and CSV `question_date` strings are preserved without inventing timestamps;
timestamps inside content are retained verbatim.

The cutoff is **exclusive**: `context[:int(end_index_in_shared_context)]`, matching
upstream inference. The loader validates bounds, then constructs a separate immutable
answer-free `QuestionInput` for each question. Later messages never reach its
embedding or LLM call, even when another question shares the context with a later
cutoff. Unknown metadata and gold fields are discarded from that contract. Empty
prefixes are allowed. Duplicate question IDs, missing context references, malformed
choices, unsupported roles/categories, and invalid cutoffs fail with sanitized errors.

## Integration API

```python
from pathlib import Path
from twin.config import Settings
from twin.evals.personamem import load_dataset, select_cases, validate_output, run_evaluation

out = validate_output(Path("/tmp/personamem-example-run"))
cases = select_cases(
    load_dataset(Path("/path/questions_32k.csv"), Path("/path/shared_contexts_32k.jsonl")),
    limit=3,
    offset=0,
)
report = run_evaluation(cases, out, Settings(), dry_run=True, score=True)
```

`load_dataset(questions_path: Path, contexts_path: Path) -> tuple[Case, ...]`;
`select_cases(cases, *, limit=3, offset=0) -> tuple[Case, ...]`;
`validate_output(out: Path) -> Path`;
`run_evaluation` accepts the selected cases, output path and Settings, with
`dry_run`, `score`, `fingerprints`, and `system` keyword options. The default system
is `twin`; pass `system="retrieval"` for the previous baseline. The Python API's
scoring default remains `score=False`.

The CLI runs exact choice scoring automatically:

```bash
uv run twin --config /path/twin.toml eval-personamem --questions /path/questions_32k.csv --contexts /path/shared_contexts_32k.jsonl --out /tmp/personamem-run-01 --limit 3
```

Add `--dry-run` to validate inputs and plan subjects without constructing a backend
or making build, embedding, answer, or judge calls. Add `--system retrieval` to run
the old baseline. The CLI uses `[llm]` for profile building and prediction,
overriding production `[chat_llm]` only in memory. On y15 this reuses
xjjk `gpt-5.6-sol` and `TWIN_LLM_KEY` from the existing env file, without calling
DeepSeek or changing production configuration. Embeddings still use `[embed]`.
Direct Python calls with `system="twin"` also use the supplied `settings.llm` for
building and answering, overriding `chat_llm` in the isolated Settings; only the
retrieval path uses `settings.effective_chat_llm`. The default selection is three
questions, preserving CSV order. Use matching question/context sizes. No data is downloaded automatically.
Download untrusted data into a new empty directory; run tools from the trusted
repository, pass data paths as arguments, and use isolated Python (`-I`) to inspect it.

The caller can supply SHA-256 digests under `questions_sha256`, `contexts_sha256`,
`dataset_sha256`, `configuration`, or `runtime_configuration`. Digests must be 64
lowercase hex characters; unsupported fields fail. Live runs compute the actual
backend/settings `runtime_configuration` digest. Dataset hashes must be supplied by
the caller from the original bytes. No raw paths, endpoint credentials, or backend
identities are included in provenance.

## Prediction and scoring

The default twin path applies the exclusive cutoff before production chat parsing
and `PersonaStore.put_source`, then calls `build_profile`, `index_persona`, and
`PersonaChat.reply(..., persist=False)`. The question, choices, and requested output
format are ordinary user-message content. The model response is the unmodified
`ChatReply.reply`, with its abstention, confidence, citations, and retrieved IDs
retained. Replies are not written back as new history. Empty or all-blank prefixes
use the production no-evidence reply or abstention; natural abstention is not a
backend failure.

Before parsing, the runtime copies Settings and replaces the database path, test
identity, and aliases. It creates a fresh private evaluation database; it never
copies, reads, or falls back to the production database. Connections and temporary
databases are cleaned up on completion or failure. Within one run, only the same
person with the exact same legal history prefix, identity mapping, build settings,
and embedding configuration can share preparation. A shared context ID alone is
insufficient: a later cutoff must never reuse a future profile for an earlier one.
Closing a connection retains the cached private database for reopening, and failed
preparation is cached to prevent repeated paid builds. There is no implicit cache
reuse across runs.

Deterministic choice parsing supplies selection and format-failure metadata only.
It must not normalize the response before scoring, repair it with another model
call, or skip official scoring solely because its format parser rejected it.
With `score=True`, the original reply goes directly to `official_score`, matching
upstream `Evaluation.extract_answer`: use the suffix after the last `<final_answer>`,
remove a terminal closing tag, extract parenthesized choice letters (or standalone
letters when none are parenthesized), require exactly the gold singleton set, and
retain upstream's full-response fallback. That fallback can accept some ambiguous
free-form responses; a format failure and an official correct result can therefore
coexist. No judge backend is constructed.

Only `--system retrieval` uses the previous per-question BM25/dense RRF retrieval:
1,500 content characters per chunk, at most 12 excerpts, 12,000 serialized evidence
characters, and RRF constant 60. Excerpts return to historical order. Its structured
`selection` response is converted to canonical `<final_answer>(x)` text. These
retrieval limits and structured-output behavior do not describe the default twin
path, which reuses the production persona and retrieval implementation.

## Private artifacts and accounting

Use a fresh output directory **outside every Git repository**. Existing artifacts
or symlinks are rejected before backend construction. Run directories are `0700`;
all artifacts are `0600`, reserved exclusively before any backend construction:

- `hypotheses.jsonl`: question ID, `model_response`, parsed `predicted_answer`, and
  `selection`; no gold. For twin, `model_response` is the original PersonaChat reply,
  including replies that do not follow the requested answer format.
- `records.jsonl`: question category, status, retrieval references, predictions, and
  score. Only scored successful records contain `correct_answer` and `gold_selection`
  for private grading; these never enter system inputs.
- `report.json`: `system`, `system_label`, `protocol_version`, totals, all seven
  question-type categories, applicable retrieval settings, provenance hashes, and
  budget-stop flag.
- `calls.jsonl` and `usage.json`: existing local usage accounting, with hashed backend
  and model identities and sanitized error types; no prompts or exception details.

Dry runs validate inputs and write private artifacts with **zero backend construction
and zero calls**, regardless of `score`. Scoring-disabled runs retain no gold in
artifacts. Prediction/setup failures are recorded per question with sanitized errors.
The existing usage recorder enforces configured budgets; a question interrupted by
a budget stop is a prediction failure, while subsequent questions are `budget_skipped`.
Unknown provider pricing follows the existing usage recorder's policy.

Building a profile can require multiple model calls before indexing and answering.
Preparation checks `BuildReport.failures`: a partial build is a preparation failure,
not a successful incomplete persona. Preparation and indexing errors are recorded
as preparation failures; stage timing helps locate the failure, with answer failures
and scoring outcomes recorded separately. Usage stages are
`persona.preparation`, `persona.index`, and `persona.answer`; shared build usage is
charged once, not once per question. Runtime metadata includes `preparation_key`,
`cache_hit`, `stages` (seconds), and preparation-failure information. The previous
single-prediction cost estimates and three-question retrieval results exclude the
new build costs and cannot establish the new pipeline's cost or quality.

`selected`, `completed`, `prediction_failures`, `missing`, `scored`, `unscored`, and
`correct` have separate counts. `missing` covers dry-run and budget-skipped questions.
`accuracy_selected` is correct / selected, counting failed or skipped live scored
questions against the denominator. `accuracy_scored` is correct / successfully scored
questions. Both are null when scoring is disabled or in dry runs; the scored accuracy
is null when no question was scored. The same counts and denominators are reported
for every `question_type`; empty groups have null accuracy. `pending` records work
remaining in incremental reports.

## Verification

The twin path has passed offline production-pipeline verification using invented
fixtures and offline backends, exercising real parse → import → profile → index →
reply behavior. Coverage includes target-role checks, prefix-cache isolation,
partial-build failure handling, cleanup, stage accounting, and zero-call dry runs,
alongside loader, scorer, and retrieval checks. The live three-question production
validation is recorded separately in [validation and failure analysis](BENCHMARK_VALIDATION.md).
Neither offline checks nor the nonrandom live sample establish full benchmark accuracy;
actual costs remain unknown because pricing was not configured.
The project checks are:

```sh
uv run ruff check src tests deploy
uv run ruff format --check src tests deploy
uv run mypy
uv run pytest -q
git diff --check
```
