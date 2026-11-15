"""Stage S5: Synthesize community troubleshooting threads into strict-schema reference diagnoses via own LLM."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from openai import OpenAI

from src.common import (
    DEFECT_TAXONOMY,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_SCHEMA_DIR,
    encode_image_as_data_url,
    init_llm_client,
    load_config,
    load_environment,
    make_record_id,
    read_json,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_json,
)
from src.filter import is_valid_comment, unwrap_raw_thread


class AuthorPseudonymizer:
    """Maps raw forum usernames to deterministic per-thread pseudonyms (author_1, author_2, ...)."""

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}

    def pseudonymize(self, raw_author: Any) -> str:
        if not isinstance(raw_author, str):
            return "deleted_user"
        cleaned = raw_author.strip()
        if not cleaned or cleaned.lower() in {"[deleted]", "[removed]", "none"}:
            return "deleted_user"
        if cleaned not in self._mapping:
            self._mapping[cleaned] = f"author_{len(self._mapping) + 1}"
        return self._mapping[cleaned]


def _extract_reply_context(
    replies: list[dict[str, Any]],
    pseudonymizer: AuthorPseudonymizer,
    *,
    levels_remaining: int,
) -> list[dict[str, Any]]:
    """Build up to N levels of reply context under a comment."""
    if levels_remaining <= 0 or not isinstance(replies, list):
        return []
    out: list[dict[str, Any]] = []
    for rep in replies:
        if not isinstance(rep, dict):
            continue
        sub_replies = _extract_reply_context(
            rep.get("replies") or [],
            pseudonymizer,
            levels_remaining=levels_remaining - 1,
        )
        if not is_valid_comment(rep) and not sub_replies:
            continue
        out.append(
            {
                "id": str(rep.get("id") or ""),
                "author": pseudonymizer.pseudonymize(rep.get("author")),
                "body": "" if not is_valid_comment(rep) else str(rep.get("body") or ""),
                "score": int(rep.get("score") or 0),
                "depth": int(rep.get("depth") or 0),
                "is_submitter": bool(rep.get("is_submitter")),
                "replies": sub_replies,
            }
        )
    return out


def prepare_thread_for_synthesis(
    raw_thread: dict[str, Any],
    *,
    top_comments_limit: int = 40,
    max_reply_context_levels: int = 2,
) -> tuple[dict[str, Any], set[str]]:
    """Construct pseudonymized post + selected comments input per S5 specification."""
    thread = unwrap_raw_thread(raw_thread)
    post = thread["post"]
    comments_tree = thread.get("comments") or []

    pseudonymizer = AuthorPseudonymizer()
    # Register post submitter first if present so OP consistently gets author_1
    if post.get("author"):
        pseudonymizer.pseudonymize(post.get("author"))

    all_flattened: list[dict[str, Any]] = []
    all_valid_ids: set[str] = set()
    submitter_comment_ids: set[str] = set()

    def _walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            cid = str(node.get("id") or "").strip()
            valid = is_valid_comment(node)
            if cid and valid:
                all_valid_ids.add(cid)
                if bool(node.get("is_submitter")):
                    submitter_comment_ids.add(cid)
                all_flattened.append(
                    {
                        "id": cid,
                        "author": pseudonymizer.pseudonymize(node.get("author")),
                        "body": str(node.get("body") or ""),
                        "score": int(node.get("score") or 0),
                        "depth": int(node.get("depth") or 0),
                        "parent_id": node.get("parent_id"),
                        "is_submitter": bool(node.get("is_submitter")),
                        "reply_context": _extract_reply_context(
                            node.get("replies") or [],
                            pseudonymizer,
                            levels_remaining=max_reply_context_levels,
                        ),
                    }
                )
                # Also collect valid IDs inside reply_context
            replies = node.get("replies") or []
            if isinstance(replies, list) and replies:
                _walk(replies)

    _walk(comments_tree if isinstance(comments_tree, list) else [])

    # Selection rule:
    # 1) Top N comments by score
    by_score = sorted(all_flattened, key=lambda c: c["score"], reverse=True)
    selected_ids: set[str] = {c["id"] for c in by_score[:top_comments_limit]}

    # 2) Every submitter comment regardless of score
    # 3) All direct replies under submitter comments regardless of score
    for c in all_flattened:
        if c["is_submitter"]:
            selected_ids.add(c["id"])
        parent_id = str(c.get("parent_id") or "")
        # Normalize Reddit t1_ prefix if present
        clean_parent = parent_id[3:] if parent_id.startswith("t1_") else parent_id
        if clean_parent in submitter_comment_ids:
            selected_ids.add(c["id"])

    selected_comments = [c for c in by_score if c["id"] in selected_ids]

    images_meta = [
        {
            "index": idx,
            "width": img.get("width"),
            "height": img.get("height"),
            "caption": img.get("caption"),
        }
        for idx, img in enumerate(post.get("images") or [])
        if isinstance(img, dict)
    ]

    prepared = {
        "subreddit": post.get("subreddit"),
        "title": post.get("title") or "",
        "body": post.get("body") or "",
        "flair": post.get("flair"),
        "upvote_ratio": post.get("upvote_ratio"),
        "images": images_meta,
        "selected_comments_count": len(selected_comments),
        "total_valid_comments": len(all_flattened),
        "comments": selected_comments,
    }
    return prepared, all_valid_ids


SYSTEM_PROMPT = f"""You are an expert 3D-printing troubleshooting analyst synthesizing a forum discussion AND its attached print photographs into a structured reference diagnosis.

Follow these strict synthesis rules:
1. Weight comments by score: a highly upvoted comment represents community-validated advice; a low-score or negative-score contradicting comment is noise.
2. Mark "solved": true ONLY when the post flair explicitly indicates resolution (e.g., "Solved" or "Print Fixed") OR the submitter's own comments (is_submitter: true) explicitly confirm that a suggested fix resolved the issue (e.g., "that worked", "fixed", "solved", "thank you, that was it"). NEVER infer solved: true merely from general commenter agreement.
3. If commenters meaningfully disagree on the defect or root cause, record the majority position in "community_consensus", explicitly name the disagreement, and set "confidence": "low".
4. ONLY include "likely_causes" and "recommended_fixes" that were actually proposed in the provided thread comments or post. Do NOT inject outside knowledge or your own unmentioned opinions.
5. Classify "defect_class" into exactly one of: {", ".join(DEFECT_TAXONOMY)}.
   - Use "overhang_curling" for curled overhangs, sagging bridges, or deformed steep overhangs/bosses from insufficient part cooling.
   - If "defect_class" is "other", set "defect_class_free" to a short label (2-5 words). Otherwise set "defect_class_free" to null.
6. Set "printer_context" ONLY from static setup parameters stated in the INITIAL POST title/body (printer model, slicer, filament/material, nozzle diameter, temperatures, speeds). NEVER extract post-hoc troubleshooting findings from comments and NEVER mention the defect or root cause in "printer_context". Set to null if no setup parameters appear in the initial post.
7. Order "likely_causes" most likely first (max 5 items) and "recommended_fixes" most actionable first (max 5 items).
8. "community_consensus" must be a concise 2-4 sentence summary of what commenters agreed on (and any disagreement).
9. "evidence_comment_ids" must contain ONLY exact comment "id" strings from the provided thread that support the diagnosis.
10. VISUAL AUDIT OF ATTACHED IMAGES (when images are attached):
   - Inspect every attached image (Image 0, Image 1, ...) and populate "image_roles" with one entry per attached image:
     * "failed_print": clearly depicts a 3D-printed object with a visible print defect/failure (including side-by-side comparison photos where a defective print is visible).
     * "clean_print": ONLY use this when the photograph, viewed completely in isolation with ZERO thread context, shows a completed, visibly defect-free 3D print (NO hanging strings/wisps, NO lifted/warped corners, NO rough blobs/underextruded gaps, and NOT a mid-print view of open raw infill cells).
     * "ambiguous_or_partial": an "improved" print that still has minor visible flaws (strings, rough walls, slight lift) OR a mid-print shot of open infill grid that looks ambiguous in isolation.
     * "hardware_closeup": depicts printer hardware/components only (nozzles, extruder gears, BLTouch wiring, bare build plate, spools) without a failed print object.
     * "slicer_or_ui": screenshot of slicer preview, firmware UI, or graphs.
     * "other": unrelated photo or meme.
   - Set "shows_failed_print": true ONLY if at least one attached image has role == "failed_print" (if no images are attached, set true).
   - Multi-image gallery handling:
     * If all failed_print images depict the SAME failure, set "gallery_split": false and omit "gallery_items".
     * ONLY if separate images in a multi-image gallery depict DIFFERENT distinct print defect classes that should become separate benchmark tasks, set "gallery_split": true and populate "gallery_items" with per-image diagnoses ({{image_index, defect_class, defect_class_free, likely_causes, recommended_fixes, include_in_eval}}).

Respond with ONLY a single valid JSON object conforming to this schema:
{{
  "defect_class": "string (enum)",
  "defect_class_free": "string or null",
  "printer_context": "string or null",
  "likely_causes": ["string (max 5)"],
  "recommended_fixes": ["string (max 5)"],
  "community_consensus": "string (2-4 sentences)",
  "confidence": "high | medium | low",
  "solved": true,
  "evidence_comment_ids": ["comment_id"],
  "shows_failed_print": true,
  "image_roles": [{{"image_index": 0, "role": "failed_print"}}],
  "gallery_split": false
}}"""


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_THINK_TAG_RE = re.compile(r"<(?:thought|think)>.*?</(?:thought|think)>", re.IGNORECASE | re.DOTALL)


def extract_message_text(content: Any) -> str:
    """Extract plain text from an OpenAI-compatible message.content (supports str or reasoning block list)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type == "thinking":
                continue
            text_val = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if isinstance(text_val, str):
                parts.append(text_val)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def parse_json_response(raw_text: Any) -> dict[str, Any]:
    """Parse JSON object from LLM output, stripping <thought>/<think> blocks and Markdown code fences."""
    cleaned = _THINK_TAG_RE.sub("", extract_message_text(raw_text)).strip()
    if cleaned.startswith("```"):
        cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            obj = json.loads(cleaned[start : end + 1])
        else:
            raise
    if not isinstance(obj, dict):
        raise ValueError("LLM response must be a JSON object")
    return obj


def validate_synthesis_output(
    candidate: dict[str, Any],
    validator: Draft202012Validator,
    valid_comment_ids: set[str] | None = None,
) -> list[str]:
    """Validate synthesis output against synthesis.schema.json and optional comment ID membership."""
    errors: list[str] = []
    for err in sorted(validator.iter_errors(candidate), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{loc}: {err.message}")

    if valid_comment_ids is not None and isinstance(candidate.get("evidence_comment_ids"), list):
        unknown = [
            cid for cid in candidate["evidence_comment_ids"]
            if isinstance(cid, str) and cid not in valid_comment_ids
        ]
        if unknown:
            errors.append(
                f"evidence_comment_ids contains IDs not in thread: {unknown}"
            )
    return errors


CLEAN_ISOLATION_SYSTEM_PROMPT = """You are a strict visual QA filter curating negative-control ("clean print") images for a 3D-print defect detector.
Inspect ONLY the attached photograph in complete isolation with zero text context.
Set "is_defect_free_finished_print": true ONLY if ALL of the following hold:
1. It clearly shows a completed 3D-printed object or completed solid first-layer test print (it MAY rest on a build plate or desk, but MUST NOT be mid-print exposed raw internal infill grid cells, and MUST NOT be printer hardware/nozzles/UI without a printed object).
2. There are ZERO visible print defects (no hanging filament strings or wisps, no lifted/warped corners or brims, no blobs/zits, no layer shifts, no rough underextrusion gaps or chewed surfaces).
If ANY string, rough defect, corner lift, exposed internal infill grid, or hardware-only subject is visible, you MUST set "is_defect_free_finished_print": false.

Return ONLY valid JSON: {"is_defect_free_finished_print": true, "reason": "short explanation"}"""


def verify_clean_print_in_isolation(
    llm_client: OpenAI,
    *,
    model: str,
    image_path: Path,
) -> bool:
    """Verify with zero thread context that a candidate clean_print image is genuinely defect-free finished."""
    try:
        resp = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CLEAN_ISOLATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Does this photo show a completed, visibly defect-free 3D print in isolation?"},
                        {"type": "image_url", "image_url": {"url": encode_image_as_data_url(image_path)}},
                    ],
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        obj = parse_json_response(resp.choices[0].message.content)
        return bool(obj.get("is_defect_free_finished_print") is True)
    except Exception:
        return False


def synthesize_single_thread(
    llm_client: OpenAI,
    *,
    model: str,
    raw_thread: dict[str, Any],
    validator: Draft202012Validator,
    image_paths: list[tuple[int, Path]] | None = None,
    verify_clean_in_isolation: bool = False,
    top_comments_limit: int = 40,
    max_reply_context_levels: int = 2,
    max_retries_on_schema_error: int = 1,
    temperature: float = 0.1,
) -> tuple[dict[str, Any], int]:
    """Synthesize one raw thread (plus downloaded images if present) with strict JSON Schema check and 1 retry."""
    prepared, valid_ids = prepare_thread_for_synthesis(
        raw_thread,
        top_comments_limit=top_comments_limit,
        max_reply_context_levels=max_reply_context_levels,
    )
    user_payload = json.dumps(prepared, ensure_ascii=False, indent=2)
    valid_imgs = [(idx, p) for idx, p in (image_paths or []) if p.is_file()]

    if valid_imgs:
        user_content: Any = [
            {
                "type": "text",
                "text": (
                    f"Synthesize the following troubleshooting thread and inspect the {len(valid_imgs)} "
                    f"attached image(s) (in order: {[idx for idx, _ in valid_imgs]}) into strict JSON:\n\n"
                    f"{user_payload}"
                ),
            }
        ]
        for img_idx, img_path in valid_imgs:
            user_content.append({"type": "text", "text": f"[Attached Image index={img_idx}]"})
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(img_path)},
                }
            )
    else:
        user_content = f"Synthesize the following troubleshooting thread into strict JSON:\n\n{user_payload}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_attempts = 1 + max(0, max_retries_on_schema_error)
    last_errors: list[str] = []
    last_raw = ""

    for attempt in range(1, max_attempts + 1):
        resp = llm_client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        last_raw = extract_message_text(resp.choices[0].message.content)

        try:
            parsed = parse_json_response(last_raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_errors = [f"JSON parse error: {exc}"]
        else:
            last_errors = validate_synthesis_output(parsed, validator, valid_comment_ids=valid_ids)
            if not last_errors:
                if verify_clean_in_isolation and valid_imgs and isinstance(parsed.get("image_roles"), list):
                    path_by_idx = dict(valid_imgs)
                    verified_one_clean = False
                    for role_entry in parsed["image_roles"]:
                        if isinstance(role_entry, dict) and role_entry.get("role") == "clean_print":
                            if verified_one_clean:
                                # Only need to isolation-verify at most 1 clean negative control per post
                                role_entry["role"] = "ambiguous_or_partial"
                                continue
                            im_p = path_by_idx.get(int(role_entry.get("image_index", -1)))
                            if im_p is not None and verify_clean_print_in_isolation(
                                llm_client, model=model, image_path=im_p
                            ):
                                verified_one_clean = True
                            else:
                                role_entry["role"] = "ambiguous_or_partial"
                return parsed, attempt

        if attempt < max_attempts:
            err_report = "; ".join(last_errors)
            messages.append({"role": "assistant", "content": last_raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON output failed strict schema validation with the following error(s): "
                        f"{err_report}\n"
                        f"Valid comment IDs in this thread are: {sorted(valid_ids)[:80]}\n"
                        "Return ONLY the corrected JSON object conforming strictly to the schema."
                    ),
                }
            )

    raise ValueError(f"Synthesis validation failed after {max_attempts} attempt(s): {'; '.join(last_errors)}")


def run_synthesize(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    schema_dir: Path = DEFAULT_SCHEMA_DIR,
    llm_client: OpenAI | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    api_key_env: str | None = None,
    max_threads: int | None = None,
    overwrite: bool = False,
    concurrency: int = 1,
    verify_clean_in_isolation: bool | None = None,
) -> dict[str, Any]:
    """Run S5 comment synthesis over accepted filtered threads (or all raw_threads if filtered missing)."""
    load_environment()
    logger = logging.getLogger("failed_print_eval")

    synth_cfg = config.get("synthesis", {})
    base_url = (
        base_url_override
        or os.environ.get("LLM_BASE_URL")
        or str(synth_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"))
    )
    model = (
        model_override
        or os.environ.get("SYNTHESIS_MODEL")
        or str(synth_cfg.get("model", "gemini-3.5-flash"))
    )
    temperature = float(synth_cfg.get("temperature", 0.1))
    top_k = int(synth_cfg.get("top_comments_limit", 40))
    reply_levels = int(synth_cfg.get("max_reply_context_levels", 2))
    schema_retries = int(synth_cfg.get("max_retries_on_schema_error", 1))

    schema = read_json(schema_dir / "synthesis.schema.json")
    validator = Draft202012Validator(schema)

    if llm_client is None:
        llm_client = init_llm_client(base_url, api_key_env=api_key_env)
        do_clean_verify = True if verify_clean_in_isolation is None else verify_clean_in_isolation
    else:
        do_clean_verify = False if verify_clean_in_isolation is None else verify_clean_in_isolation

    records_dir = data_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    # Map record_id -> ordered [(image_index, Path)] from assets.jsonl so S5 visually inspects every photo
    assets_by_record: dict[str, list[tuple[int, Path]]] = {}
    for asset in read_jsonl(data_dir / "assets.jsonl"):
        rel = str(asset.get("path") or "")
        full_img = data_dir / rel
        if rel and full_img.is_file():
            rec_key = str(asset["record_id"])
            assets_by_record.setdefault(rec_key, []).append((int(asset.get("image_index", 0)), full_img))
    for rec_key in assets_by_record:
        assets_by_record[rec_key].sort(key=lambda pair: pair[0])

    filtered_rows = read_jsonl(data_dir / "filtered_threads.jsonl")
    work_items: list[tuple[str, Path]] = []
    if filtered_rows:
        for row in filtered_rows:
            rec_id = str(row["record_id"])
            raw_rel = str(row.get("raw_path") or "")
            raw_path = data_dir / raw_rel
            if raw_path.is_file():
                work_items.append((rec_id, raw_path))
    else:
        raw_dir = data_dir / "raw_threads"
        for raw_path in sorted(raw_dir.glob("*.json")) if raw_dir.is_dir() else []:
            payload = unwrap_raw_thread(read_json(raw_path))
            post = payload["post"]
            rec_id = make_record_id(str(post.get("subreddit", "reddit")), str(post.get("id", raw_path.stem)))
            work_items.append((rec_id, raw_path))

    if max_threads is not None:
        work_items = work_items[:max_threads]

    first_try_passed = 0
    retry_passed = 0
    failed = 0
    skipped = 0

    to_run: list[tuple[int, str, Path]] = []
    for idx, (rec_id, raw_path) in enumerate(work_items, start=1):
        out_path = records_dir / f"{rec_id}.json"
        if out_path.is_file() and not overwrite:
            skipped += 1
            continue
        to_run.append((idx, rec_id, raw_path))

    def _process_one(item: tuple[int, str, Path]) -> tuple[str, int | None]:
        idx, rec_id, raw_path = item
        out_path = records_dir / f"{rec_id}.json"
        raw_thread = read_json(raw_path)
        local_validator = Draft202012Validator(schema)
        try:
            synthesis, attempts = synthesize_single_thread(
                llm_client,
                model=model,
                raw_thread=raw_thread,
                validator=local_validator,
                image_paths=assets_by_record.get(rec_id),
                verify_clean_in_isolation=do_clean_verify,
                top_comments_limit=top_k,
                max_reply_context_levels=reply_levels,
                max_retries_on_schema_error=schema_retries,
                temperature=temperature,
            )
        except Exception as exc:
            logger.error("[synthesize] (%d/%d) Failed %s: %s", idx, len(work_items), rec_id, exc)
            return rec_id, None

        record_payload = {
            "record_id": rec_id,
            "model": model,
            "synthesized_at": utc_now_iso(),
            "attempts": attempts,
            "synthesis": synthesis,
        }
        write_json(out_path, record_payload)
        logger.info(
            "[synthesize] (%d/%d) %s -> defect=%s conf=%s solved=%s failed_print=%s (imgs=%d, attempts=%d)",
            idx,
            len(work_items),
            rec_id,
            synthesis["defect_class"],
            synthesis["confidence"],
            synthesis["solved"],
            synthesis.get("shows_failed_print", True),
            len(assets_by_record.get(rec_id, [])),
            attempts,
        )
        return rec_id, attempts

    workers = max(1, int(concurrency))
    if workers == 1:
        outcomes = [_process_one(it) for it in to_run]
    else:
        outcomes = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(_process_one, it) for it in to_run]):
                outcomes.append(fut.result())

    for _, attempts in outcomes:
        if attempts is None:
            failed += 1
        elif attempts == 1:
            first_try_passed += 1
        else:
            retry_passed += 1

    attempted = first_try_passed + retry_passed + failed
    passed = first_try_passed + retry_passed
    pass_rate = (passed / attempted) if attempted > 0 else 1.0

    logger.info(
        "[synthesize] Complete | attempted=%d | passed=%d (first_try=%d, retry=%d) | failed=%d | skipped=%d | pass_rate=%.1f%%",
        attempted,
        passed,
        first_try_passed,
        retry_passed,
        failed,
        skipped,
        pass_rate * 100.0,
    )
    return {
        "stage": "synthesize",
        "model": model,
        "base_url": base_url,
        "attempted": attempted,
        "passed": passed,
        "first_try_passed": first_try_passed,
        "retry_passed": retry_passed,
        "failed": failed,
        "skipped_existing": skipped,
        "validation_pass_rate": round(pass_rate, 4),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S5: Synthesize comments into reference diagnosis JSON.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR, help="Path to schema directory")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible LLM base URL")
    parser.add_argument("--model", default=None, help="Synthesizer model name")
    parser.add_argument("--api-key-env", default=None, help="Env var name holding the LLM API key")
    parser.add_argument("--max-threads", type=int, default=None, help="Max threads to synthesize")
    parser.add_argument("--overwrite", action="store_true", help="Re-synthesize existing records")
    parser.add_argument("--concurrency", type=int, default=4, help="Parallel LLM worker threads")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_synthesize(
        config,
        data_dir=args.data_dir,
        schema_dir=args.schema_dir,
        base_url_override=args.base_url,
        model_override=args.model,
        api_key_env=args.api_key_env,
        max_threads=args.max_threads,
        overwrite=args.overwrite,
        concurrency=args.concurrency,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
