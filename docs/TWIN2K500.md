# Twin-2K-500 benchmark

This adapter predicts held-out wave 4 responses using only a participant's wave 1–3
material. The default `--system twin` imports that material into an isolated
evaluation database, then runs Twin's production profile building, indexing, and
PersonaChat. Select `--system retrieval` explicitly for the previous BM25 persona-text
baseline. Reports identify the system and protocol version; the two systems' results
must remain separate.

## Verified sources and schema

Verified on 2026-10-08 against the public
[dataset card](https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500/blob/main/README.md),
[wave_split files](https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500/tree/main/wave_split/chunks),
and the first public parquet chunk (294 participants; 28,188 response items),
validated through native parquet loading, JSON export, and streaming JSONL export.
The pinned source revision is `f883165a3026fde855dfd448e0cd16443ab257b6`.
The original `wave_split/chunks/wave_persona_chunk_001.parquet` SHA-256 is
`dd92be4ac50d3476dc0166f7b6b2fdb07ff6e167c379f62d1b7730905135753b`.
The dataset is CC BY 4.0;
retain attribution to Toubia, Gui, Peng, Merlau, Li and Chen when using it.
Downloaded records belong outside git; repository tests contain invented data only.

Each row has `pid` (integer in the inspected chunk) and four string columns:
`wave1_3_persona_text`, `wave1_3_persona_json`, `wave4_Q_wave1_3_A`,
`wave4_Q_wave4_A`. The three JSON columns encode lists of blocks with
`ElementType: "Block"`, `BlockName`, `BlockType` and `Questions` lists.
Questions have `QuestionID`, `QuestionText`, `QuestionType`, type-specific
metadata, and `Answers`. Observed wave 4 response types:

| Type | Question metadata | Gold response | Adapter behavior |
| --- | --- | --- | --- |
| MC | `Options`, `Settings.Selector` SAVR/SAHR | `SelectedByPosition` (1-based), `SelectedText` | Single categorical item |
| Matrix | `Rows`, `Columns`, optional `RowsID`, SubSelector SingleAnswer | Parallel position/text arrays | One categorical case per row |
| Slider | `Statements`, optional `StatementsID`, `Range.Min/Max/Ticks` | `Values`, numeric strings | One numeric case per statement |
| TE | `Settings.ContentType: ValidNumber` | `Text`, numeric string | Numeric item with no inferred range |
| DB | `QuestionText`, `is_descriptive` | No response | Answer-free block instructions included as context |

Past-wave JSON also has TE `Answers.Text` lists of single-key labeled text-entry
objects. The old retrieval text fallback retains their text values while dropping
labels and unknown metadata; it omits past questions with empty text because their
answers lack an interpretable question. The twin path can also carry whitelisted
past-wave questionnaire structure in its answer-free input, preserving question and
answer relationships. This is historical evidence only; future gold and comparator
answers are separate grading data.

The inspected first participant has 64 question objects: 53 MC, 5 Matrix,
2 Slider, 3 TE and 1 DB, expanded into 98 response items. Participant assignments
and forms vary. Missing row/statement IDs use 1-based positional IDs, matching the
[official JSON converter](https://github.com/tianyipeng-lab/Digital-Twin-Simulation/blob/main/evaluation/json2csv.py).
Unsupported response forms remain explicitly unscored rather than receiving an
invented scale. Malformed response arrays, domains and duplicate IDs are rejected.

`wave4_Q_wave4_A.Answers` becomes separate `Gold`, never model input.
`wave4_Q_wave1_3_A` is used only as an optional human test-retest comparator,
matched by question and item IDs with identical question text, choices and ranges.
Comparator alignment compares question metadata only; added past-wave history fields
must not affect that alignment. Neither wave 4 answers nor comparator answers are
imported into the persona database.
Unknown future-wave columns and question metadata are discarded. Rows containing
`persona_text`, `persona_json` or `persona_summary` are rejected: `full_persona`
uses repeated wave 4 answers and would leak test responses. Wave-split column
names are a provenance boundary; the adapter cannot detect future answers manually
inserted into a field mislabeled as past-wave text.

## API and local input

```python
from pathlib import Path
from twin.config import load_settings
from twin.evals.twin2k500 import load_dataset, select_cases, run_evaluation

cases = load_dataset(Path("/private/tmp/twin-data/wave_split.json"))
selected = select_cases(cases, participant_ids=["71"], limit=3, offset=0)
report = run_evaluation(
    selected,
    Path("/private/tmp/twin-runs/new-run"),
    load_settings(),
    dry_run=True,
    score=True,
)
```

`load_dataset(path) -> tuple[Case, ...]` accepts a JSON list of exported official
wave-split rows, a JSONL file containing one official row per line, a parquet
chunk, or a dataset folder containing `wave_split/chunks/*.parquet`.
A wave_split/chunks folder itself also works. JSONL is parsed line by line;
blank lines are ignored. Empty files and malformed rows fail with sanitized errors.
JSON/JSONL export folders are discovered in filename order, including a
`wave_split/chunks` layout. Parquet files take precedence when present; keep
unrelated catalog JSON and duplicate exports elsewhere. Parsing is streamed for
JSONL, but validated response cases are still materialized by the public API.
Parquet requires optional `pyarrow`; no new runtime dependency is added. For example, export the official Hugging Face `wave_split`
`data` split with `json.dump(list(split), stream)` outside this repository.
No downloaded scripts need to be executed. A standalone optional converter can
stream official parquet rows into a fresh external JSONL file without changing
project dependencies. Run this trusted inline code from the repository directory;
pass the downloaded input and a new output path as arguments:

```sh
uv run --no-project --with pyarrow python -I -c '
import json, os, sys
import pyarrow.parquet as pq
fd = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as output:
    for batch in pq.ParquetFile(sys.argv[1]).iter_batches(batch_size=1):
        for row in batch.to_pylist():
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
' /private/tmp/twin-download/wave_persona_chunk_001.parquet /private/tmp/twin-export/wave_split.jsonl
```

Create the external output directory beforehand. The converter never executes
code from the dataset and refuses to overwrite an existing output file.

The shared CLI enables native scoring automatically; there is no `--score` switch:

```sh
uv run twin eval-twin2k500 --dataset /private/tmp/twin-export/wave_split.jsonl \
  --out /private/tmp/twin-runs/fresh-jsonl-run --limit 3 --dry-run
```

All three benchmark CLI commands (LongMemEval, PersonaMem, Twin-2K-500) use
`_benchmark_settings` to copy Settings, set `chat_llm=settings.llm`, and clear
`judges`. Thus the configured `[llm]` xjjk `gpt-5.6-sol` is used instead of the
production `[chat_llm]` DeepSeek for profile building and answering when that
configuration is supplied. Production configuration and its DeepSeek selection are
unchanged. Embedding uses `[embed]`. In direct Python calls, `system="twin"` also uses
`settings.llm` for both building and answering, overriding `chat_llm` in the isolated
settings; only `system="retrieval"` retains `settings.effective_chat_llm` behavior.
The scoring default is `score=True`. Add `--system retrieval` to select the old
baseline; otherwise the CLI and runner default to `twin`.

Previously completed first-chunk JSONL verification: all 294 participants and 28,188 response
items loaded (24,072 categorical, 4,116 numeric), with zero missing gold answers
and 28,188 aligned comparator answers. The CLI dry-run with `--limit 3` exited
successfully: selected 3, completed 0, prediction failures 0, missing 3, pending 0,
and usage calls 0. Existing loader tests cover mixed JSON/JSONL directory discovery
and streaming JSONL reads. These earlier checks establish the input contract.
The new production pipeline has separately passed offline verification with invented
fixtures, exercising import, profile building, indexing, and PersonaChat replies.
Live production validation completed on 2026-10-09: one item using Kimi and two
other items using gpt-6-luna. Results remain separate by model; see
[validation and failure analysis](BENCHMARK_VALIDATION.md) for outcomes and limitations.
These nonrandom samples do not establish full benchmark accuracy; actual costs remain unknown.

`select_cases(cases, *, limit=3, offset=0, participant_ids=None)` filters explicit
participant IDs first, then slices response items in source order. IDs are strings
in the API. Unknown IDs fail. Without a participant filter, selection starts with
the first source participant; the default limit is three response items, not three
people. Matrix rows and Slider statements each count toward the limit.

`run_evaluation` accepts cases, output path, Settings, and the `dry_run`, `score`,
`fingerprints`, and `system` keyword options. `QuestionInput` holds only whitelisted
question metadata and past evidence; `Case.gold` holds actual and comparator answers.
Dry runs validate input and plan subjects without constructing backends, building
profiles, or making any model or embedding calls.

## Default twin pipeline and costs

Wave 1–3 material is represented as native `ParsedSource` / `Expression` questionnaire
data marked as self-report, then passed through `PersonaStore.put_source`,
`build_profile`, `index_persona`, and `PersonaChat.reply(..., persist=False)`.
Structured past-wave evidence preserves question-answer relationships as self-report;
plain text remains supported as attributed questionnaire material marked
`narrated=True`, without treating it as verbatim statements by the participant or
guessing unreliable question boundaries. The adapter does not pretend questionnaire answers are chat
messages or force them into Twin's specialized facet-tagged questionnaire syntax.
`facets_hint` is empty: the adapter does not open sensitive dimensions, and production
default consent remains in effect. Production target-only extraction, indexing, and
retrieval remain unchanged.

Settings are copied and the database path, test identity, and aliases replaced before
input conversion. The runtime creates fresh private evaluation databases; it never
copies, reads, or falls back to the production database. All questions for one
participant with identical legal past evidence, identity mapping, build settings,
and embedding configuration share one preparation within a run. Closed connections
are reopened against the cached private database instead of rebuilding; failed
preparation is also cached to prevent repeated paid builds. Connections close after
each question and temporary databases are cleaned up at the end, including on error.
There is no implicit cross-run cache.

Questions, choices, and output requirements are ordinary user-message content.
Predictions come directly from `ChatReply.reply`; abstention, confidence, citations,
and retrieved IDs are retained, and replies are not persisted into history. Strict
label or number parsing records ambiguous output as a format failure without guessing
a label or calling another model to repair it. Empty evidence uses the production
no-evidence reply or abstention, which is not itself a backend failure.

Preparation checks `BuildReport.failures`; partial builds cannot silently proceed
as successful profiles. Preparation and indexing errors are recorded as preparation
failures, with stage timing to help locate them; answer failures and scoring outcomes
are recorded separately. Runtime metadata includes `preparation_key`, `cache_hit`,
`stages` (seconds), and preparation-failure information. Usage stages are
`persona.preparation`, `persona.index`, and `persona.answer`; shared preparation is
charged only once. Building can require multiple model calls before indexing and
prediction. Prior three-question retrieval runs and single-prediction cost estimates
do not measure this pipeline or include building costs. The live production sample's
stage calls and usage are recorded in [validation and failure analysis](BENCHMARK_VALIDATION.md),
including building; actual costs remain unknown because pricing was not configured.

Only `--system retrieval` uses `PersonaBaseline` over the old persona text input:
1,500-character chunks, at most eight chunks and 12,000 evidence characters per
question, including choices and block instructions. No-hit queries fall back to
source-order chunks. Gold is never used to select chunks. These limits do not
describe the default twin production retrieval path.

## Metric boundaries and outputs

The [official evaluator](https://github.com/tianyipeng-lab/Digital-Twin-Simulation/blob/main/evaluation/mad_accuracy_evaluation.py)
uses CSV mappings, manual column ranges, decile transforms for some anchoring
responses, and task/column summaries of normalized differences. Its pipeline also
contains comparisons using wave 1–3 as the reference. This adapter deliberately
reports **custom native-item metrics against wave 4**, not official MAD accuracy,
psychometric scale totals, official task scores or reliability-normalized accuracy.

Categorical scoring is exact label match; numeric category codes are never given
an MAE. Numeric predictions must be finite standalone numbers. Slider predictions
must fall within the declared range. Absolute error is aggregated as MAE only
within the same question/item, preserving native units. Slider normalized absolute
error uses its explicit range width and can be summarized across bounded items.
TE has no inferred bounds or decile conversion. Invalid/empty numeric predictions,
missing gold and unsupported types remain unscored. For a supported categorical item
with gold, a successful prediction attempt is scored: an empty reply, invalid label,
or explicit Twin abstention counts as incorrect and stays in the accuracy denominator.
Explicit abstention counts as incorrect even if the reply contains a valid label.
This applies to both the production Twin and retrieval systems; numeric abstentions
remain unscored. Dry runs, budget skips, backend construction failures, preparation
failures, answer failures, and disabled scoring retain empty scores. A missing human
test-retest answer also remains unscored. Raw replies, parsed hypotheses, Twin abstention
metadata and format-failure flags are retained independently of grading; no choice is
guessed or repaired. Coverage denominators include all selected items; scored-only
accuracy is not interpreted as full-run accuracy.

Reports include `system`, `system_label`, `protocol_version`,
selected/completed/pending counts, prediction failures, missing
predictions, missing gold, unsupported items, scored/unscored coverage, participant
and question/item groups, and the optional human comparator with its own coverage.
Dry-run human comparisons are local computations and incur no model calls.
Production identity data is never imported or modified.

Outputs are `hypotheses.jsonl`, `records.jsonl`, `report.json`, `calls.jsonl` and
`usage.json` in an external directory (0700; files 0600). Existing artifacts,
including dangling symlinks, cannot be overwritten. Hypotheses are private data;
records retain no gold answers or persona excerpts. Participant IDs, configurations
and selected-case content are hashed. The default `dataset_sha256` is a canonical
hash of selected cases, not the raw source file; callers can provide a source-file
SHA-256 in `fingerprints`. Caller-supplied `configuration` is preserved, including
CLI selection settings such as limit/offset; without it, the Settings hash is used.
After backend construction, `runtime_configuration` records a digest of the actual
selected runtime configuration. For twin this includes the production runtime's
configuration; the old retrieval path fingerprints its Settings, backend and
retrieval limits together with the caller configuration digest.
Dry runs construct no backend and generate no runtime fingerprint.
Only supported digest fields are accepted. Usage and
budget tracking reuse the LongMemEval writer, with sanitized backend failures and
hashed model/backend identities. Budget stops retain completed records and mark
remaining items skipped; configured budgets have the same provider-usage and
pricing limitations as Twin's existing accounting.
