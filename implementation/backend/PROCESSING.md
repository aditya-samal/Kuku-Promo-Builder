# Scene analysis and promo generation

Run commands from `implementation/backend`. No API or web server is needed.

## Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` in `.env`. Both commands load it automatically; existing shell environment variables take precedence. Credentials are never written into results. Calls send source text to the configured provider. Use provider terms suitable for the input's confidentiality requirements.

## 1. Parse and analyze the episodes

```sh
LLM_MODEL=gemini-3.5-flash-lite .venv/bin/python process.py \
  --input '../../I Married a Broken Soldier. He was a Duke' \
  --output data/broken-soldier-scenes --analyze --delay 7
```

Omit `--analyze` for deterministic parsing only. `--limit 3` selects the first three episodes as a pilot. All scenes are annotated in one request per episode; no per-block model calls.

| Level | Stored content |
|---|---|
| Episode | One short summary, number, source fingerprint, analysis version, model |
| Scene | Summary, overlapping tags, hooks with types, possible endings with open questions/types, context needed, payoff references where available |
| Source block | Exact text, label/speaker, type, episode-local timestamps, scene ID and stable block ID |

Annotations must cover every source scene exactly once. Hook/ending references must belong to that scene; payoff references may point to a later scene in the same episode and must follow the ending. Validation failures receive precise feedback on retry. These checks establish reference validity, not semantic truth.

There are no identity maps, alias reconciliation, character lists, or uncertainty fields. Original names in the source text remain intact.

| Path | Purpose |
|---|---|
| `sources/` | Original screenplay bytes |
| `parsed/` | Deterministic scene/block structure and source metadata |
| `analysis/` | Analysis cache, fingerprint and model metadata |
| `episodes/` | Final episode records consumed by promo generation |
| `runs/` | Unedited request/response evidence for every attempt |
| `project.json` | Current processing scope, progress and source statistics |

Existing successful results are reused only when prompt, source, model and endpoint fingerprints match. A changed analysis schema requires a new version. The former episode-only analyses are retained separately in `data/broken-soldier`; they are not used as scene annotations.

## 2. Generate and review promos

```sh
LLM_MODEL=gemini-3.5-flash-lite .venv/bin/python generate_promos.py \
  --project data/broken-soldier-scenes \
  --output data/promos-v3 --delay 7
```

For a pilot or focused rerun, add `--episodes 1,2,3`. Run only one full workflow at a time, or space concurrent development calls so combined usage stays under provider limits. The default 5-second request-start gap is about 12 RPM per process; limits also depend on tokens and daily quotas.

The actual LangGraph has these nodes:

1. `discover_windows`: deterministic retrieval/enumeration of legal windows, using scene hints but covering every possible legal source opening.
2. `propose_cuts`: LLM chooses up to two continuous ranges from those windows. A validator checks boundary IDs, duration and tags.
3. `review_cuts`: a separate LLM request assesses exact selected footage plus separately labelled surrounding context.
4. `collect_results`: deterministic quality gate on evidence and editorial scores.
5. `repair_cuts`: if no suggestion passes, ask for alternatives using rejection feedback; at most one editorial repair round.

Source-only review evidence is required in the first 3 seconds and last 8 seconds. Gemini assigns direct weighted points for hook (30), clarity (25), cliffhanger (35), and pacing (10). Acceptance requires suitability, in-cut evidence for all four criteria, and respective minimums of 25, 20, 28, and 7. These are model judgments, not calibrated ad-performance predictions.

After the per-episode graph, Python deduplicates same-episode cuts with >=70% overlap relative to the shorter cut, ranks the retained suggestions, and exports them. Dialogue-safe boundaries do not prove syntactic completeness: the reviewer must reject cuts ending mid-sentence or after an already-resolved conflict. Camera/action blocks may overlap boundaries, so visible intervals are retained separately from their original descriptions.

| Output | Purpose |
|---|---|
| `suggestions.json` | Ranked editor-facing suggestions with tags, ordered episode/time segments, hook, cliffhanger, rationale and review |
| `edit_sheet.csv` | Editor-friendly timestamp instructions |
| `edit_sheet.md` | Readable suggestions with exact selected dialogue/actions |
| `episodes/` | Final per-episode accepted/rejected results and repair counts |
| `responses/raw/` | Unedited proposals, reviews, failures and repair attempts |
| `responses/cache/` | Validated stage responses, keyed by schema/prompt/source/model/endpoint |
| `rejected.json` | Rejected final candidates and duplicates |
| `generation.json` | Coverage, failures, model calls, cache hits and scope |
| `graph.json` | Version and generated Mermaid graph |

Stages are sequential and restartable through response caches. There is no persistent LangGraph checkpointer; rerunning reconstructs graph state from cached stages. Failure records are retained, and a partially failed run exits nonzero. A completed run means every scoped episode was examined, not that every episode has a good promo.

## Scope and limitations

This version produces single-episode, continuous 20–60-second cuts. The local website supports upload, ranked results, saved selections and CSV export. Cross-episode assembly and custom prompts are outside the prototype scope. Model review is a second request to the same provider, not an independent human judgment. Script timings and visual interpretations require footage review before publication. Never treat an editor-facing score as measured conversion or watch-through performance.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover all supplied files when present, source-reference scope, scene completeness, legal durations, dialogue-safe cuts, review evidence intervals, duplicate ranking, rejection termination and caching. API scaffolding remains available for future integration; the standalone commands are the primary workflow.
