# Data Sources, Retrieval Provenance, and Usage Restrictions

## 1. Sources

This evaluation dataset pipeline collects public 3D-printing troubleshooting discussions via the [Context.dev](https://context.dev) Web Scraping API:

| Source | Platform | Role | Filtering / Notes |
| --- | --- | --- | --- |
| `https://www.reddit.com/r/FixMyPrint` | Reddit | Primary | Dedicated failed-print troubleshooting community; `Solved` flair and submitter confirmations recorded as quality signals. |
| `https://www.reddit.com/r/3Dprinting` | Reddit | Secondary | Filtered by `Troubleshooting` flair and mandatory failure lexicon (`config/lexicon.txt`). |
| `https://www.reddit.com/r/3Dprintingtech` | Reddit | Tertiary | Filtered by `Troubleshooting` flair and mandatory failure lexicon (`config/lexicon.txt`). |

*(Optional Phase 2 web forum targets documented in the specification—`forum.prusa3d.com`, `community.ultimaker.com`, and `forums.reprap.org`—are disabled by default in v1 and governed by the same restrictions below if enabled.)*

## 2. Retrieval Dates

- Every assembled evaluation record in `data/dataset/eval.jsonl` and `data/dataset/val.jsonl` carries an exact ISO-8601 UTC retrieval timestamp in `source.retrieved_at`.
- Per-thread and per-image retrieval timestamps and Context.dev `request_id` audit entries are also recorded in `data/fetch_manifest.jsonl`, `data/assets.jsonl`, and `data/credit_usage.jsonl`.
- Pilot dataset retrieval date: `2026-11-14` (UTC).

## 3. Legal and Ethical Usage Restrictions

1. **Ownership & Platform Terms**: Photographs and comments in troubleshooting threads are user-generated content owned by their respective authors and governed by Reddit's User Agreement and Terms of Service.
2. **No Public Redistribution of Images**: Scraped failure photographs (`data/images/*`) are strictly for internal evaluation and research use. **Do not publish, rehost, or redistribute scraped images publicly.** (`data/` is excluded via `.gitignore`.)
3. **External Sharing Rules**: If any benchmark metadata is shared outside the internal research team:
   - Share **only** the public `source.url` links and the synthesized reference fields (`defect_class`, `likely_causes`, `recommended_fixes`, `community_consensus`).
   - Do **not** include downloaded image files or base64 image payloads.
   - Strip all commenter pseudonyms (`author_1`, `author_2`, ...) and raw comment quotes; raw usernames are already stripped prior to synthesis (`src/synthesize.py`).
4. **No Implied License from Image Classification**: Context.dev `formats.images` classifications (such as `classification == "photography"`) describe visual content categories only and establish **nothing** regarding copyright, licensing, or usage rights.
