# 3D-Print Failure Diagnosis Eval Dataset (`failed-print-eval`)

End-to-end pipeline for discovering failed 3D-print troubleshooting threads on Reddit via [Context.dev](https://docs.context.dev), downloading failure photographs, synthesizing community comment trees into strict-schema reference diagnoses, assembling a deduplicated multimodal evaluation dataset, and scoring vision-language models with exact-match + blind randomized A/B LLM judging.

---

## Architecture

```
config/queries.yaml + config/lexicon.txt
  │
  ├─► S1 src/discover.py       ──► data/candidates.jsonl       (Context.dev prebuilt: reddit-search)
  ├─► S2 src/fetch.py          ──► data/raw_threads/*.json     (Context.dev prebuilt: reddit-post; Scrape or Batches)
  ├─► S3 src/filter.py         ──► data/filtered_threads.jsonl (Image dims, lexicon, comments, solved tag)
  │                            └──► data/discarded.jsonl
  ├─► S4 src/download.py       ──► data/images/* + assets.jsonl(Context.dev formats.bytes + SHA-256)
  ├─► S5 src/synthesize.py     ──► data/records/*.json         (Own OpenAI-compatible LLM + JSON Schema retry)
  ├─► S6 src/build_dataset.py  ──► data/dataset/{eval,val}.jsonl (Crosspost SHA-256 dedupe + 90/10 split)
  └─► S7 src/evaluate.py       ──► data/eval_runs/eval_report.{json,md} (Variant A & B + blind A/B LLM judge)
```

All stages communicate exclusively via JSON/JSONL files on disk so every intermediate artifact is inspectable and any stage can be re-run independently.

---

## Setup

Requires **Python 3.11+**.

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Configure credentials in an untracked `.env` file (never pass API keys on the command line):

```bash
cp .env.example .env
# Edit .env to set CONTEXT_DEV_API_KEY and GEMINI_API_KEY (or LLM_API_KEY / OPENAI_API_KEY)
chmod 600 .env
```

---

## Running Each Stage (CLI)

### S1 — Discovery (`src/discover.py`)
Searches `r/FixMyPrint`, `r/3Dprinting` (`Troubleshooting` flair), and `r/3Dprintingtech` using Context.dev's `reddit-search` parser and filters low-engagement, text-only, NSFW, and removed posts at discovery time:

```bash
python -m src.discover --subreddits FixMyPrint --max-queries 10 --limit 100
```

### S2 — Thread Fetch (`src/fetch.py`)
Fetches full post metadata + nested comment trees (`?sort=top`, `limit=200`) and stores verbatim `parsed.data` in `data/raw_threads/{subreddit}_{post_id}.json`. Automatically switches to Context.dev **Batches** (`input.mode="scrape"` with deterministic `Idempotency-Key`) above 200 URLs or when `--batch` is passed:

```bash
# Per-URL scrape loop (<= 200 threads)
python -m src.fetch --max-threads 100

# Asynchronous Batch submission + polling (> 200 threads or forced)
python -m src.fetch --batch
```

### S3 — Filter & Classify (`src/filter.py`)
Applies image resolution (`>= 400x300`), failure lexicon (`config/lexicon.txt`, mandatory outside `r/FixMyPrint`), and non-deleted comment count (`>= 5`) gates. Records `solved` metadata and logs all rejections with reasons to `data/discarded.jsonl`:

```bash
python -m src.filter
# Optional online photography classification for non-Reddit or mixed-chrome pages:
python -m src.filter --classify-images
```

### S4 — Image Download (`src/download.py`)
Downloads original image bytes via Context.dev `formats={"bytes": True}` (`max_age_ms=0`, 30s fail deadline), verifies `image/*` MIME types, parses dimensions, and records SHA-256 hashes in `data/assets.jsonl`:

```bash
python -m src.download --max-posts 100
```

### S5 — Multimodal Comment & Image Synthesis (`src/synthesize.py`)
Pseudonymizes commenters (`author_1`, `author_2`, ...), selects top 40 comments by score + all submitter comments + direct replies under submitter comments, **attaches all downloaded images** for visual verification (`image_roles`, `shows_failed_print`, and `gallery_items` splitting), extracts leak-free `printer_context` strictly from the initial post, validates against `config/schema/synthesis.schema.json`, and retries once with validation errors appended:

```bash
python -m src.synthesize \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-3.5-flash
```

### S6 — Dataset Assembly (`src/build_dataset.py`)
Deduplicates crossposted failures by image `sha256` (retaining the thread with highest `comment_count`), filters out `hardware_closeup` / `slicer_or_ui` images and non-defect posts (`data/dataset/excluded_non_defect.jsonl`), routes `clean_print` images into `data/dataset/negative_controls.jsonl` (`defect_class: "clean"`), validates against `config/schema/record.schema.json`, and emits `data/dataset/eval.jsonl` + 10% `data/dataset/val.jsonl` holdout (or 100% `test` with `--final-release`):

```bash
python -m src.build_dataset
# Final benchmark release (100% in eval.jsonl with splits="test"):
python -m src.build_dataset --final-release
```

### S7 — Evaluation Harness (`src/evaluate.py`)
Evaluates any OpenAI-compatible vision endpoint under:
- **Variant A (Pure Visual-only)**: **ONLY the photograph(s)** — zero `title`, `printer_context`, or `body_excerpt` (eliminating title/comment label leakage).
- **Variant B (Context-assisted)**: Photograph(s) + `title` + initial-post `printer_context` + `body_excerpt`.
- **Negative Controls**: Evaluates `data/dataset/negative_controls.jsonl` in pure-visual mode to measure `clean` Specificity and False-Alarm Rate.
- **Metrics & Judging**: Reports Strict 17-class Exact Match, Synonym-Collapsed Accuracy (`ringing/ghosting`, `stringing/oozing`), Coarse Group Accuracy (`first_layer/bed_adhesion/warping`), taxonomy confusion matrices, and multimodal reference-rubric LLM judge scores (`0–2` on causes and fixes, plus `score_pairwise_blind_ab()` for blind Model-X-vs-Model-Y comparisons). API errors are explicitly excluded from metric denominators rather than averaged as `0`:

```bash
python -m src.evaluate \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-3.5-flash-lite \
  --judge-base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --judge-model gemini-pro-latest
```

---

## One-Command Pipeline Runner

Run all stages end-to-end (or select stages with `--stages`):

```bash
# Full 100-thread pilot (S1 -> S7)
python -m src.pipeline --subreddits FixMyPrint --max-queries 10 --pilot-size 100

# Build dataset only without running S7 evaluation
python -m src.pipeline --skip-evaluate --pilot-size 100
```

---

## Cost Control & Observability

- Every Context.dev call logs `request_id`, `credits_consumed`, and `credits_remaining` to console and appends an audit record to `data/credit_usage.jsonl`.
- `cost_control.max_requests_per_run` in `config/queries.yaml` (or `--max-requests`) enforces a hard per-stage request ceiling.
- All stages are idempotent by default, skipping threads, images, and synthesis records already saved on disk unless `--overwrite` is passed.

---

## Offline Tests

Run the offline test suite (no API keys or network calls required):

```bash
pytest -v
```

---

## Risks, Limitations, and Usage Constraints

1. **Community Consensus != Physical Ground Truth**: Reference diagnoses summarize score-weighted community consensus and submitter confirmations (`solved: true`), which remain a proxy rather than controlled lab ground truth. Treat LLM judge scores comparatively across models on the same dataset.
2. **Heuristic Visual Gating**: Context.dev provides image dimensions and coarse categories (`photography` vs `logo`), not 3D-print defect semantics; S3 relies on subreddit provenance, failure lexicon, and spot checks.
3. **Gallery & Crosspost Handling**: Multi-defect galleries are flagged via `gallery_split`; crossposts sharing identical photos across subreddits are deduplicated by image `sha256` in S6.
4. **Strict Redistribution Policy**: Scraped user photographs are for internal evaluation only and must **never** be publicly redistributed. See [`NOTICE.md`](NOTICE.md) for full provenance and sharing rules.
