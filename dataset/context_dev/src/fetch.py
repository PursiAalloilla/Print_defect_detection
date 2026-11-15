"""Stage S2: Fetch full Reddit threads (post + nested comments) via Context.dev Scrape or Batches."""

from __future__ import annotations

import argparse
import copy
import hashlib
from html.parser import HTMLParser
import logging
import time
from pathlib import Path
from typing import Any

from context.dev import ContextDev, ContextDevError

from src.common import (
    BudgetExceededError,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    RunTracker,
    append_jsonl,
    init_context_client,
    load_config,
    make_record_id,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_json,
)


def build_reddit_post_url(subreddit: str, post_id: str, *, comment_sort: str = "top") -> str:
    """Construct canonical Reddit thread URL with comment sort order."""
    return f"https://www.reddit.com/r/{subreddit}/comments/{post_id}?sort={comment_sort}"


def raw_thread_filename(subreddit: str, post_id: str) -> str:
    """Return raw_threads filename {subreddit}_{post_id}.json preserving subreddit name."""
    safe_sub = "".join(ch for ch in subreddit if ch.isalnum() or ch in ("_", "-"))
    safe_id = "".join(ch for ch in post_id if ch.isalnum() or ch in ("_", "-"))
    return f"{safe_sub}_{safe_id}.json"


def compute_batch_idempotency_key(
    items: list[dict[str, str]],
    *,
    comment_sort: str,
    comment_limit: int,
) -> str:
    """Build deterministic <=200-char Idempotency-Key for a batch submission."""
    canonical = "|".join(
        sorted(f"{it['subreddit']}:{it['post_id']}" for it in items)
    ) + f"|sort={comment_sort}|limit={comment_limit}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]
    return f"fpe-s2-reddit-post-{len(items)}-{digest}"


class _ShredditCommentHTMLParser(HTMLParser):
    """Extract RedditThreadComment nodes from rendered Shreddit <shreddit-comment> DOM."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_by_id: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self._active_body_id: str | None = None
        self._div_depth: int = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): v for k, v in attrs}
        if tag_l == "shreddit-comment":
            thing_id = attr_map.get("thingid") or ""
            cid = thing_id[3:] if thing_id.startswith("t1_") else thing_id
            if not cid or cid in self.meta_by_id:
                return
            raw_parent = attr_map.get("parentid") or ""
            parent_id = raw_parent[3:] if raw_parent.startswith("t1_") else (raw_parent or None)
            author = attr_map.get("author")
            is_deleted = ("deleted" in attr_map) or (not author) or (author in {"[deleted]", "[removed]"})
            permalink = attr_map.get("permalink")
            score_str = attr_map.get("score") or ""
            depth_str = attr_map.get("depth") or ""
            award_str = attr_map.get("award-count") or ""
            self.meta_by_id[cid] = {
                "id": cid,
                "author": None if is_deleted else author,
                "body": "",
                "score": int(score_str) if score_str.lstrip("-").isdigit() else 0,
                "posted_at": attr_map.get("created"),
                "depth": int(depth_str) if depth_str.isdigit() else 0,
                "parent_id": parent_id,
                "url": f"https://www.reddit.com{permalink}" if permalink else None,
                "is_submitter": "is-op" in attr_map,
                "is_deleted": is_deleted,
                "is_collapsed": "collapsed" in attr_map,
                "award_count": int(award_str) if award_str.isdigit() else 0,
                "author_avatar_url": attr_map.get("avatar"),
                "replies": [],
            }
            self.order.append(cid)
            return

        if self._active_body_id is not None:
            if tag_l == "div":
                self._div_depth += 1
            elif tag_l in {"p", "br", "li", "blockquote", "pre"}:
                self._buf.append("\n")
            return

        if tag_l == "div":
            elem_id = attr_map.get("id") or ""
            if elem_id.startswith("t1_") and elem_id.endswith("-comment-rtjson-content"):
                cid = elem_id[3 : -len("-comment-rtjson-content")]
                if cid in self.meta_by_id:
                    self._active_body_id = cid
                    self._div_depth = 1
                    self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if self._active_body_id is not None and tag.lower() == "div":
            self._div_depth -= 1
            if self._div_depth <= 0:
                body = "\n".join(line.strip() for line in "".join(self._buf).splitlines() if line.strip())
                self.meta_by_id[self._active_body_id]["body"] = body
                self._active_body_id = None
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._active_body_id is not None:
            self._buf.append(data)


def parse_shreddit_comments_tree(html_text: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Parse nested RedditThreadComment tree from rendered Shreddit HTML (fallback when parsed.comments is empty)."""
    if not html_text or "<shreddit-comment" not in html_text:
        return []
    parser = _ShredditCommentHTMLParser()
    parser.feed(html_text)

    # Cap total comments shallowest-first to mirror prebuilt reddit-post behavior
    ordered_ids = sorted(
        parser.order,
        key=lambda cid: (parser.meta_by_id[cid]["depth"], parser.order.index(cid)),
    )[:limit]
    allowed_set = set(ordered_ids)

    roots: list[dict[str, Any]] = []
    for cid in parser.order:
        if cid not in allowed_set:
            continue
        node = parser.meta_by_id[cid]
        pid = node["parent_id"]
        if pid and pid in allowed_set:
            parser.meta_by_id[pid]["replies"].append(node)
        else:
            roots.append(node)
    return roots


def _merge_html_comments_if_needed(
    parsed_data: dict[str, Any],
    html_block: Any,
    *,
    comment_limit: int,
) -> dict[str, Any]:
    """Preserve parsed_data verbatim unless comments came back empty and rendered HTML has comments."""
    existing_comments = parsed_data.get("comments")
    if isinstance(existing_comments, list) and len(existing_comments) > 0:
        return parsed_data

    html_success = getattr(html_block, "success", False) if html_block is not None else False
    html_data = getattr(html_block, "data", None) if html_block is not None else None
    if not html_success or not isinstance(html_data, str):
        return parsed_data

    recovered = parse_shreddit_comments_tree(html_data, limit=comment_limit)
    if not recovered:
        return parsed_data

    merged = copy.deepcopy(parsed_data)
    merged["comments"] = recovered
    return merged


def _fetch_via_loop(
    client: ContextDev,
    tracker: RunTracker,
    *,
    to_fetch: list[dict[str, str]],
    raw_dir: Path,
    manifest_path: Path,
    comment_sort: str,
    comment_limit: int,
    logger: logging.Logger,
) -> tuple[int, int]:
    """Fetch threads one by one via client.web.scrape."""
    succeeded = 0
    failed = 0

    for idx, item in enumerate(to_fetch, start=1):
        try:
            tracker.check_budget(1)
        except BudgetExceededError as exc:
            logger.warning("%s", exc)
            break

        subreddit = item["subreddit"]
        post_id = item["post_id"]
        out_path = Path(item["out_path"])
        thread_url = build_reddit_post_url(subreddit, post_id, comment_sort=comment_sort)

        try:
            page = client.web.scrape(
                url=thread_url,
                formats={"parse": True, "html": True},
                parse_params={
                    "type": "prebuilt",
                    "parser": "reddit-post",
                    "limit": comment_limit,
                },
                shared_params={"wait_for": "shreddit-comment"},
                tags=["failed-print-eval", "s2-fetch"],
            )
        except ContextDevError as exc:
            tracker.handle_sdk_error(exc, operation="reddit-post", target=thread_url)
            failed += 1
            continue

        req_id, credits_used = tracker.record_response(page, operation="reddit-post", target=thread_url)
        if not page.parsed.success or not isinstance(page.parsed.data, dict):
            logger.warning(
                "[fetch] (%d/%d) Parse failed for %s | request_id=%s | error_code=%s | message=%s",
                idx,
                len(to_fetch),
                thread_url,
                req_id,
                page.parsed.error_code,
                page.parsed.message,
            )
            failed += 1
            continue

        thread_payload = _merge_html_comments_if_needed(
            page.parsed.data, getattr(page, "html", None), comment_limit=comment_limit
        )
        write_json(out_path, thread_payload)
        retrieved_at = utc_now_iso()
        append_jsonl(
            manifest_path,
            {
                "record_id": make_record_id(subreddit, post_id),
                "subreddit": subreddit,
                "post_id": post_id,
                "url": thread_url,
                "raw_path": str(out_path.relative_to(raw_dir.parent)),
                "retrieved_at": retrieved_at,
                "request_id": req_id,
                "credits_consumed": credits_used,
                "mode": "scrape",
            },
        )
        succeeded += 1

    return succeeded, failed


def _fetch_via_batch(
    client: ContextDev,
    tracker: RunTracker,
    *,
    to_fetch: list[dict[str, str]],
    raw_dir: Path,
    manifest_path: Path,
    comment_sort: str,
    comment_limit: int,
    poll_interval_sec: float,
    max_wait_sec: float,
    resume_batch_id: str | None,
    idempotency_key_override: str | None,
    logger: logging.Logger,
) -> tuple[int, int, str]:
    """Submit or resume a Context.dev Scrape batch for thread fetching and save verbatim results."""
    item_lookup: dict[str, dict[str, str]] = {
        f"{it['subreddit']}_{it['post_id']}": it for it in to_fetch
    }

    if resume_batch_id:
        batch_id = resume_batch_id
        logger.info("[fetch] Resuming existing batch_id=%s", batch_id)
    else:
        tracker.check_budget(len(to_fetch))
        idem_key = idempotency_key_override or compute_batch_idempotency_key(
            to_fetch, comment_sort=comment_sort, comment_limit=comment_limit
        )
        urls_payload = [
            {
                "url": build_reddit_post_url(
                    it["subreddit"], it["post_id"], comment_sort=comment_sort
                ),
                "item_id": f"{it['subreddit']}_{it['post_id']}",
                "meta": {"subreddit": it["subreddit"], "post_id": it["post_id"]},
            }
            for it in to_fetch
        ]
        # Disable automatic retries on state-changing batch submission; idempotency_key guards manual retries
        submit_client = client.with_options(max_retries=0)
        try:
            batch_sub = submit_client.batch.submit(
                input={
                    "mode": "scrape",
                    "data": {
                        "formats": {"parse": True, "html": True},
                        "parse_params": {
                            "type": "prebuilt",
                            "parser": "reddit-post",
                            "limit": comment_limit,
                        },
                        "shared_params": {"wait_for": "shreddit-comment"},
                        "urls": urls_payload,
                    },
                },
                idempotency_key=idem_key,
                tags=["failed-print-eval", "s2-fetch-batch"],
            )
        except ContextDevError as exc:
            tracker.handle_sdk_error(exc, operation="batch.submit", target=f"{len(urls_payload)} urls")
            raise

        tracker.record_response(batch_sub, operation="batch.submit", target=batch_sub.id)
        batch_id = batch_sub.id
        logger.info(
            "[fetch] Submitted batch_id=%s | status=%s | submitted=%s | reserved_pages=%s | credits_reserved=%s | invalid_urls=%d",
            batch_sub.id,
            batch_sub.status,
            getattr(batch_sub.input, "submitted", None),
            getattr(batch_sub.input, "reserved", None),
            getattr(batch_sub.credits, "reserved", None),
            len(batch_sub.invalid_urls or []),
        )

    # Poll until batch reaches a terminal state
    terminal_states = {"completed", "cancelled", "failed"}
    deadline = time.monotonic() + max_wait_sec
    final_batch = None

    while True:
        try:
            status_resp = client.batch.retrieve(batch_id)
        except ContextDevError as exc:
            tracker.handle_sdk_error(exc, operation="batch.retrieve", target=batch_id)
            raise

        tracker.record_response(status_resp, operation="batch.retrieve", target=batch_id)
        prog = status_resp.progress
        logger.info(
            "[fetch] Batch %s status=%s | succeeded=%s failed=%s pending=%s",
            batch_id,
            status_resp.status,
            getattr(prog, "succeeded", None),
            getattr(prog, "failed", None),
            getattr(prog, "pending", None),
        )
        if status_resp.status in terminal_states:
            final_batch = status_resp
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Batch {batch_id} did not reach terminal state within {max_wait_sec}s "
                f"(last status={status_resp.status}). Resume later with --resume-batch-id {batch_id}."
            )
        time.sleep(poll_interval_sec)

    credits_obj = final_batch.credits
    net_credits = int(getattr(credits_obj, "net", None) or getattr(credits_obj, "reserved", 0) or 0)
    tracker.credits_consumed += net_credits
    logger.info(
        "[fetch] Batch %s settled | status=%s | credits_reserved=%s refunded=%s net=%d",
        batch_id,
        final_batch.status,
        getattr(credits_obj, "reserved", None),
        getattr(credits_obj, "refunded", None),
        net_credits,
    )

    if final_batch.status != "completed":
        logger.warning(
            "[fetch] Batch %s ended with status=%s (failure=%s)",
            batch_id,
            final_batch.status,
            final_batch.failure,
        )
        if final_batch.status == "failed" and getattr(final_batch.progress, "succeeded", 0) == 0:
            return 0, len(to_fetch), batch_id

    # Read paginated results
    succeeded = 0
    failed = 0
    cursor: str | None = None

    while True:
        kwargs: dict[str, Any] = {"limit": 100}
        if cursor is not None:
            kwargs["cursor"] = cursor
        page_res = client.batch.get_results(batch_id, **kwargs)
        tracker.record_response(page_res, operation="batch.get_results", target=batch_id)

        for record in page_res.data or []:
            item_key = getattr(record, "item_id", None) or ""
            meta = getattr(record, "meta", None) or {}
            info = item_lookup.get(item_key)
            subreddit = (
                info["subreddit"]
                if info
                else str(meta.get("subreddit") or (item_key.split("_", 1)[0] if "_" in item_key else "reddit"))
            )
            post_id = (
                info["post_id"]
                if info
                else str(meta.get("post_id") or (item_key.split("_", 1)[1] if "_" in item_key else item_key))
            )
            out_path = Path(info["out_path"]) if info else (raw_dir / raw_thread_filename(subreddit, post_id))

            if record.status != "ok":
                logger.warning(
                    "[fetch] Batch item %s failed | error_code=%s | message=%s",
                    item_key,
                    getattr(record, "error_code", None),
                    getattr(record, "message", None),
                )
                failed += 1
                continue

            parsed_block = record.result.parsed
            if not parsed_block.success or not isinstance(parsed_block.data, dict):
                logger.warning(
                    "[fetch] Batch item %s parse failed | request_id=%s | error_code=%s | message=%s",
                    item_key,
                    record.result.request_id,
                    parsed_block.error_code,
                    parsed_block.message,
                )
                failed += 1
                continue

            thread_payload = _merge_html_comments_if_needed(
                parsed_block.data, getattr(record.result, "html", None), comment_limit=comment_limit
            )
            write_json(out_path, thread_payload)
            append_jsonl(
                manifest_path,
                {
                    "record_id": make_record_id(subreddit, post_id),
                    "subreddit": subreddit,
                    "post_id": post_id,
                    "url": record.url,
                    "raw_path": str(out_path.relative_to(raw_dir.parent)),
                    "retrieved_at": utc_now_iso(),
                    "request_id": record.result.request_id,
                    "credits_consumed": int(getattr(record, "credits_used", 1) or 1),
                    "batch_id": batch_id,
                    "mode": "batch",
                },
            )
            succeeded += 1

        if not page_res.has_more or not page_res.next_cursor:
            break
        cursor = page_res.next_cursor

    return succeeded, failed, batch_id


def run_fetch(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    client: ContextDev | None = None,
    max_threads: int | None = None,
    comment_limit_override: int | None = None,
    force_batch: bool = False,
    resume_batch_id: str | None = None,
    idempotency_key: str | None = None,
    overwrite: bool = False,
    max_requests_override: int | None = None,
) -> dict[str, Any]:
    """Run S2 thread fetch over candidates.jsonl, storing verbatim raw_threads/*.json."""
    logger = logging.getLogger("failed_print_eval")
    own_client = client is None
    if client is None:
        client = init_context_client(config)

    max_requests = int(
        max_requests_override
        if max_requests_override is not None
        else config.get("cost_control", {}).get("max_requests_per_run", 250)
    )
    tracker = RunTracker(stage="fetch", max_requests=max_requests, data_dir=data_dir, logger=logger)

    fetch_cfg = config.get("fetch", {})
    comment_sort = str(fetch_cfg.get("comment_sort", "top"))
    comment_limit = int(
        comment_limit_override if comment_limit_override is not None else fetch_cfg.get("comment_limit", 200)
    )
    comment_limit = max(1, min(1000, comment_limit))
    batch_threshold = int(fetch_cfg.get("batch_threshold", 200))
    poll_interval_sec = float(fetch_cfg.get("batch_poll_interval_sec", 15.0))
    max_wait_sec = float(fetch_cfg.get("batch_max_wait_sec", 1800.0))

    candidates_path = data_dir / "candidates.jsonl"
    raw_dir = data_dir / "raw_threads"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = data_dir / "fetch_manifest.jsonl"

    candidates = read_jsonl(candidates_path)
    if max_threads is not None:
        candidates = candidates[:max_threads]

    to_fetch: list[dict[str, str]] = []
    skipped_existing = 0

    for cand in candidates:
        post_id = str(cand.get("id") or "").strip()
        subreddit = str(cand.get("subreddit") or "FixMyPrint").strip()
        if not post_id:
            continue
        out_path = raw_dir / raw_thread_filename(subreddit, post_id)
        if out_path.is_file() and not overwrite:
            skipped_existing += 1
            continue
        to_fetch.append(
            {
                "subreddit": subreddit,
                "post_id": post_id,
                "out_path": str(out_path),
            }
        )

    use_batch = bool(force_batch or resume_batch_id or len(to_fetch) > batch_threshold)
    batch_id_used: str | None = None
    succeeded = 0
    failed = 0

    try:
        if not to_fetch and not resume_batch_id:
            logger.info(
                "[fetch] Nothing to fetch (candidates=%d, skipped_existing=%d).",
                len(candidates),
                skipped_existing,
            )
        elif use_batch:
            logger.info(
                "[fetch] Using Batches mode for %d threads (threshold=%d, force_batch=%s)",
                len(to_fetch),
                batch_threshold,
                force_batch,
            )
            succeeded, failed, batch_id_used = _fetch_via_batch(
                client,
                tracker,
                to_fetch=to_fetch,
                raw_dir=raw_dir,
                manifest_path=manifest_path,
                comment_sort=comment_sort,
                comment_limit=comment_limit,
                poll_interval_sec=poll_interval_sec,
                max_wait_sec=max_wait_sec,
                resume_batch_id=resume_batch_id,
                idempotency_key_override=idempotency_key,
                logger=logger,
            )
        else:
            logger.info("[fetch] Fetching %d threads via per-URL Scrape (skipped_existing=%d)", len(to_fetch), skipped_existing)
            succeeded, failed = _fetch_via_loop(
                client,
                tracker,
                to_fetch=to_fetch,
                raw_dir=raw_dir,
                manifest_path=manifest_path,
                comment_sort=comment_sort,
                comment_limit=comment_limit,
                logger=logger,
            )
    finally:
        if own_client:
            client.close()

    summary = tracker.log_summary()
    summary.update(
        {
            "mode": "batch" if use_batch else "scrape",
            "batch_id": batch_id_used,
            "candidates_considered": len(candidates),
            "skipped_existing": skipped_existing,
            "attempted": len(to_fetch),
            "succeeded": succeeded,
            "failed": failed,
        }
    )
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S2: Fetch full Reddit threads via Context.dev.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument("--max-threads", type=int, default=None, help="Maximum candidate threads to consider")
    parser.add_argument("--comment-limit", type=int, default=None, help="Max comments per thread (1..1000)")
    parser.add_argument("--batch", action="store_true", help="Force asynchronous Batches mode even below 200 URLs")
    parser.add_argument("--resume-batch-id", default=None, help="Resume polling and reading an existing batch ID")
    parser.add_argument("--idempotency-key", default=None, help="Explicit Idempotency-Key for batch submission")
    parser.add_argument("--overwrite", action="store_true", help="Re-fetch threads already on disk")
    parser.add_argument("--max-requests", type=int, default=None, help="Override max_requests_per_run")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_fetch(
        config,
        data_dir=args.data_dir,
        max_threads=args.max_threads,
        comment_limit_override=args.comment_limit,
        force_batch=args.batch,
        resume_batch_id=args.resume_batch_id,
        idempotency_key=args.idempotency_key,
        overwrite=args.overwrite,
        max_requests_override=args.max_requests,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
