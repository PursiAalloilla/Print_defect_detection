"""Stage S3: Apply post-level and optional image-level gates; label solved status and log rejections."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

from context.dev import ContextDev, ContextDevError

from src.common import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_LEXICON_PATH,
    RunTracker,
    init_context_client,
    load_config,
    make_record_id,
    read_json,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_jsonl,
)


def load_lexicon_patterns(lexicon_path: Path = DEFAULT_LEXICON_PATH) -> list[re.Pattern[str]]:
    """Compile case-insensitive regex patterns from config/lexicon.txt."""
    patterns: list[re.Pattern[str]] = []
    with lexicon_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(re.compile(line, re.IGNORECASE))
    return patterns


def unwrap_raw_thread(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either verbatim parsed.data ({post, comments}) or full scrape wrapper ({parsed: {data: ...}})."""
    if "post" in payload and isinstance(payload["post"], dict):
        return payload
    parsed = payload.get("parsed")
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
        return parsed["data"]
    raise ValueError("Thread JSON does not contain a 'post' object")


def is_valid_comment(comment: dict[str, Any]) -> bool:
    """Return True if a comment is non-deleted, non-AutoModerator, and has substantive body text."""
    if bool(comment.get("is_deleted")):
        return False
    author = str(comment.get("author") or "").strip().lower()
    if author == "automoderator":
        return False
    body = (comment.get("body") or "").strip()
    if not body or body.lower() in {"[deleted]", "[removed]"}:
        return False
    return True


def iter_comments_dfs(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten nested RedditThreadComment tree in depth-first order."""
    flat: list[dict[str, Any]] = []
    stack = list(reversed(comments))
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        flat.append(node)
        replies = node.get("replies") or []
        if isinstance(replies, list) and replies:
            stack.extend(reversed(replies))
    return flat


def matches_lexicon(title: str, body: str | None, patterns: list[re.Pattern[str]]) -> str | None:
    """Return the first matching regex pattern string if title or body matches, else None."""
    haystack = f"{title}\n{body or ''}"
    for pat in patterns:
        if pat.search(haystack):
            return pat.pattern
    return None


_NEGATED_SOLVED_RE = re.compile(
    r"\b(?:unsolved|not\s+solved|isn'?t\s+solved|not\s+fixed|didn'?t\s+fix|did\s+not\s+fix|didn'?t\s+work|did\s+not\s+work|still\s+broken)\b",
    re.IGNORECASE,
)

_CELEBRATORY_SHOWCASE_TITLE_RE = re.compile(
    r"(?:\bnothing\s+to\s+fix\b"
    r"|^\s*thank(?:s|\s+you)\b"
    r"|\bjust\s+wanna\s+say\s+thank\s+you\b"
    r"|\bi\s+was\s+successful\b"
    r"|\bfinally\s+fixed\s+my\s+print\b"
    r"|\blooking\s+gorgeous\b"
    r"|\bi\s+present\s+to\s+you\b"
    r"|\bpeak\s+bed\s+adhesion\b"
    r"|\bworks\s+flawlessly\b"
    r"|\b1st\s+layer\s+heaven\b)",
    re.IGNORECASE,
)


def detect_solved_status(
    post: dict[str, Any],
    flat_comments: list[dict[str, Any]],
    *,
    flair_keywords: list[str],
    submitter_phrases: list[str],
) -> tuple[bool, str | None]:
    """Determine solved status from post flair or submitter confirmation comments."""
    flair = str(post.get("flair") or "").strip()
    if flair and not _NEGATED_SOLVED_RE.search(flair):
        for kw in flair_keywords:
            if re.search(rf"\b{re.escape(kw)}\b", flair, re.IGNORECASE):
                return True, f"flair:{flair}"

    for comment in flat_comments:
        if not bool(comment.get("is_submitter")) or not is_valid_comment(comment):
            continue
        body = str(comment.get("body") or "")
        for phrase in submitter_phrases:
            pat = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            for match in pat.finditer(body):
                # Check nearby context window for explicit negation
                window_start = max(0, match.start() - 25)
                window_end = min(len(body), match.end() + 15)
                snippet = body[window_start:window_end]
                if not _NEGATED_SOLVED_RE.search(snippet):
                    return True, f"submitter_comment:{comment.get('id')}"

    return False, None


def evaluate_thread(
    raw_thread: dict[str, Any],
    *,
    lexicon_patterns: list[re.Pattern[str]],
    subreddit_rules: dict[str, dict[str, Any]],
    min_image_width: int = 400,
    min_image_height: int = 300,
    min_non_deleted_comments: int = 5,
    solved_flair_keywords: list[str] | None = None,
    solved_submitter_phrases: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate one raw Reddit thread against S3 post-level gates and return structured decision."""
    thread = unwrap_raw_thread(raw_thread)
    post = thread["post"]
    comments = thread.get("comments") or []

    post_id = str(post.get("id") or "")
    subreddit = str(post.get("subreddit") or "FixMyPrint")
    record_id = make_record_id(subreddit, post_id)

    reasons: list[str] = []

    if bool(post.get("is_nsfw")):
        reasons.append("nsfw")
    if post.get("removed_by") is not None:
        reasons.append(f"removed_by:{post.get('removed_by')}")
    if _CELEBRATORY_SHOWCASE_TITLE_RE.search(str(post.get("title") or "")):
        reasons.append("celebratory_followup_showcase")

    # Gate 1: At least one image >= min_image_width x min_image_height
    raw_images = post.get("images") or []
    qualifying_images: list[dict[str, Any]] = []
    for idx, img in enumerate(raw_images):
        if not isinstance(img, dict):
            continue
        img_url = str(img.get("url") or "").strip()
        w = img.get("width")
        h = img.get("height")
        if (
            img_url.startswith(("http://", "https://"))
            and isinstance(w, (int, float))
            and isinstance(h, (int, float))
            and int(w) >= min_image_width
            and int(h) >= min_image_height
        ):
            qualifying_images.append(
                {
                    "original_index": idx,
                    "url": img_url,
                    "width": int(w),
                    "height": int(h),
                    "caption": img.get("caption"),
                }
            )

    if not qualifying_images:
        reasons.append("no_qualifying_image")

    # Gate 2: Failure lexicon (r/FixMyPrint passes on provenance alone)
    sub_rule = subreddit_rules.get(subreddit.lower(), {})
    require_lexicon = bool(
        sub_rule.get("require_lexicon", subreddit.lower() != "fixmyprint")
    )
    matched_pattern = matches_lexicon(
        str(post.get("title") or ""),
        post.get("body"),
        lexicon_patterns,
    )
    if require_lexicon and matched_pattern is None:
        reasons.append("lexicon_mismatch")

    # Gate 3: Non-deleted comment count >= min_non_deleted_comments
    flat_comments = iter_comments_dfs(comments if isinstance(comments, list) else [])
    valid_comments = [c for c in flat_comments if is_valid_comment(c)]
    if len(valid_comments) < min_non_deleted_comments:
        reasons.append(f"insufficient_non_deleted_comments:{len(valid_comments)}")

    # Thread quality labeling
    flair_kws = solved_flair_keywords if solved_flair_keywords is not None else ["solved"]
    sub_phrases = (
        solved_submitter_phrases
        if solved_submitter_phrases is not None
        else ["that worked", "fixed", "solved", "thank you, that was it"]
    )
    solved, solved_source = detect_solved_status(
        post,
        flat_comments,
        flair_keywords=flair_kws,
        submitter_phrases=sub_phrases,
    )

    scores = [int(c["score"]) for c in valid_comments if isinstance(c.get("score"), (int, float))]
    min_comment_score = min(scores) if scores else 0

    return {
        "accepted": len(reasons) == 0,
        "reasons": reasons,
        "record_id": record_id,
        "post_id": post_id,
        "subreddit": subreddit,
        "url": str(post.get("url") or f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/"),
        "title": str(post.get("title") or ""),
        "flair": post.get("flair"),
        "score": int(post.get("score") or 0),
        "upvote_ratio": post.get("upvote_ratio"),
        "comment_count": int(post.get("comment_count") or len(valid_comments)),
        "non_deleted_comment_count": len(valid_comments),
        "min_comment_score": min_comment_score,
        "lexicon_match": matched_pattern,
        "solved": solved,
        "solved_source": solved_source,
        "accepted_images": qualifying_images,
        "crosspost_parent_id": post.get("crosspost_parent_id"),
    }


def enrich_and_filter_images_online(
    client: ContextDev,
    tracker: RunTracker,
    *,
    thread_url: str,
    min_width: int,
    min_height: int,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Optional S3 image-level classification via formats.images + imageParams."""
    tracker.check_budget(1)
    try:
        page = client.web.scrape(
            url=thread_url,
            formats={"images": True},
            image_params={
                "enrich": ["dimensions", "classification", "file"],
                "dedupe": "visual",
            },
            tags=["failed-print-eval", "s3-image-classify"],
        )
    except ContextDevError as exc:
        tracker.handle_sdk_error(exc, operation="images-classify", target=thread_url)
        return None, None

    req_id, _ = tracker.record_response(page, operation="images-classify", target=thread_url)
    if not page.images.success or page.images.data is None:
        logger.warning(
            "[filter] Image classification failed for %s | request_id=%s | error_code=%s",
            thread_url,
            req_id,
            page.images.error_code,
        )
        return None, req_id

    photos: list[dict[str, Any]] = []
    for idx, img in enumerate(page.images.data):
        if img.classification != "photography":
            continue
        w = int(img.width or 0)
        h = int(img.height or 0)
        if w < min_width or h < min_height:
            continue
        photos.append(
            {
                "original_index": idx,
                "url": img.url,
                "file_url": img.file_url,
                "width": w,
                "height": h,
                "classification": img.classification,
                "caption": img.alt,
            }
        )
    return photos, req_id


def run_filter(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    classify_images: bool | None = None,
    client: ContextDev | None = None,
    max_requests_override: int | None = None,
) -> dict[str, Any]:
    """Run S3 filtering over raw_threads/*.json, writing filtered_threads.jsonl and discarded.jsonl."""
    logger = logging.getLogger("failed_print_eval")
    filter_cfg = config.get("filter", {})
    min_width = int(filter_cfg.get("min_image_width", 400))
    min_height = int(filter_cfg.get("min_image_height", 300))
    min_comments = int(filter_cfg.get("min_non_deleted_comments", 5))
    flair_kws = list(filter_cfg.get("solved_flair_keywords", ["solved"]))
    sub_phrases = list(
        filter_cfg.get(
            "solved_submitter_phrases",
            ["that worked", "fixed", "solved", "thank you, that was it"],
        )
    )
    use_img_classify = (
        classify_images
        if classify_images is not None
        else bool(filter_cfg.get("enable_image_classification", False))
    )

    subreddit_rules = {
        str(s["name"]).lower(): s for s in config.get("subreddits", []) if "name" in s
    }
    lexicon_patterns = load_lexicon_patterns(lexicon_path)

    # Load fetch_manifest to preserve retrieved_at timestamps
    manifest_rows = read_jsonl(data_dir / "fetch_manifest.jsonl")
    retrieved_at_by_record = {
        str(r["record_id"]): str(r["retrieved_at"])
        for r in manifest_rows
        if "record_id" in r and "retrieved_at" in r
    }

    raw_dir = data_dir / "raw_threads"
    raw_files = sorted(raw_dir.glob("*.json")) if raw_dir.is_dir() else []

    own_client = False
    tracker: RunTracker | None = None
    if use_img_classify:
        max_requests = int(
            max_requests_override
            if max_requests_override is not None
            else config.get("cost_control", {}).get("max_requests_per_run", 250)
        )
        tracker = RunTracker(stage="filter", max_requests=max_requests, data_dir=data_dir, logger=logger)
        if client is None:
            client = init_context_client(config)
            own_client = True

    accepted_rows: list[dict[str, Any]] = []
    discarded_rows: list[dict[str, Any]] = []
    rejection_Breakdown: dict[str, int] = {}

    try:
        for raw_path in raw_files:
            raw_payload = read_json(raw_path)
            decision = evaluate_thread(
                raw_payload,
                lexicon_patterns=lexicon_patterns,
                subreddit_rules=subreddit_rules,
                min_image_width=min_width,
                min_image_height=min_height,
                min_non_deleted_comments=min_comments,
                solved_flair_keywords=flair_kws,
                solved_submitter_phrases=sub_phrases,
            )
            decision["raw_path"] = str(raw_path.relative_to(data_dir))
            decision["retrieved_at"] = retrieved_at_by_record.get(
                decision["record_id"], utc_now_iso()
            )

            if decision["accepted"] and use_img_classify and client is not None and tracker is not None:
                photos, req_id = enrich_and_filter_images_online(
                    client,
                    tracker,
                    thread_url=decision["url"],
                    min_width=min_width,
                    min_height=min_height,
                    logger=logger,
                )
                decision["image_classify_request_id"] = req_id
                if photos is not None:
                    if not photos:
                        decision["accepted"] = False
                        decision["reasons"].append("no_photography_image")
                    else:
                        decision["accepted_images"] = photos

            if decision["accepted"]:
                accepted_rows.append(decision)
            else:
                discarded_rows.append(decision)
                for r in decision["reasons"]:
                    key = r.split(":", 1)[0]
                    rejection_Breakdown[key] = rejection_Breakdown.get(key, 0) + 1
    finally:
        if own_client and client is not None:
            client.close()

    filtered_path = data_dir / "filtered_threads.jsonl"
    discarded_path = data_dir / "discarded.jsonl"
    write_jsonl(filtered_path, accepted_rows)
    write_jsonl(discarded_path, discarded_rows)

    solved_count = sum(1 for r in accepted_rows if r["solved"])
    logger.info(
        "[filter] Processed %d threads -> accepted=%d (solved=%d), discarded=%d | reasons=%s",
        len(raw_files),
        len(accepted_rows),
        solved_count,
        len(discarded_rows),
        rejection_Breakdown,
    )

    summary: dict[str, Any] = {
        "stage": "filter",
        "total_threads": len(raw_files),
        "accepted": len(accepted_rows),
        "solved_accepted": solved_count,
        "discarded": len(discarded_rows),
        "rejection_breakdown": rejection_Breakdown,
        "filtered_path": str(filtered_path),
        "discarded_path": str(discarded_path),
    }
    if tracker is not None:
        summary.update(tracker.log_summary())
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S3: Filter raw threads and classify solved status.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--lexicon", type=Path, default=DEFAULT_LEXICON_PATH, help="Path to lexicon.txt")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument(
        "--classify-images",
        action="store_true",
        help="Enable optional Context.dev formats.images photography classification",
    )
    parser.add_argument("--max-requests", type=int, default=None, help="Override max_requests_per_run")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_filter(
        config,
        data_dir=args.data_dir,
        lexicon_path=args.lexicon,
        classify_images=True if args.classify_images else None,
        max_requests_override=args.max_requests,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
