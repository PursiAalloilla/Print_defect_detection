"""Stage S1: Discover troubleshooting candidate threads on Reddit via Context.dev reddit-search parser."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from context.dev import ContextDev, ContextDevError

from src.common import (
    BudgetExceededError,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    RunTracker,
    init_context_client,
    load_config,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_jsonl,
)


def build_reddit_search_url(
    subreddit: str,
    query: str,
    *,
    sort: str = "top",
    time_range: str = "all",
    flair_filter: str | None = None,
) -> str:
    """Build a subreddit-restricted Reddit search URL."""
    effective_query = f'{query} flair:"{flair_filter}"' if flair_filter else query
    params = urlencode(
        {
            "q": effective_query,
            "sort": sort,
            "t": time_range,
            "restrict_sr": "1",
        }
    )
    return f"https://www.reddit.com/r/{subreddit}/search?{params}"


def filter_search_post(
    post: dict[str, Any],
    *,
    allowed_types: set[str],
    min_comment_count: int,
    min_score: int,
    drop_nsfw: bool = True,
    drop_removed: bool = True,
    flair_filter: str | None = None,
    excluded_flairs: set[str] | None = None,
) -> tuple[bool, str | None]:
    """Apply S1 discovery-time filters to a single RedditPost dict from reddit-search."""
    post_id = post.get("id")
    if not isinstance(post_id, str) or not post_id.strip():
        return False, "missing_id"

    post_type = str(post.get("type") or "")
    if post_type not in allowed_types:
        return False, f"excluded_type:{post_type}"

    if drop_nsfw and bool(post.get("is_nsfw")):
        return False, "nsfw"

    if drop_removed and post.get("removed_by") is not None:
        return False, f"removed_by:{post.get('removed_by')}"

    comment_count = int(post.get("comment_count") or 0)
    if comment_count < min_comment_count:
        return False, f"low_comments:{comment_count}"

    score = int(post.get("score") or 0)
    if score < min_score:
        return False, f"low_score:{score}"

    flair_val = str(post.get("flair") or "").strip()
    if excluded_flairs and flair_val and flair_val.lower() in excluded_flairs:
        return False, f"excluded_flair:{flair_val}"

    if flair_filter:
        if flair_filter.lower() not in flair_val.lower():
            return False, f"flair_mismatch:{flair_val}"

    return True, None


def candidate_from_post(
    post: dict[str, Any],
    *,
    fallback_subreddit: str,
    query: str,
    sort: str,
    time_range: str,
    request_id: str | None,
) -> dict[str, Any]:
    """Convert a surviving reddit-search post dict into a candidates.jsonl record."""
    subreddit = str(post.get("subreddit") or fallback_subreddit)
    post_id = str(post["id"])
    url = str(post.get("url") or f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/")
    return {
        "id": post_id,
        "subreddit": subreddit,
        "url": url,
        "type": post.get("type"),
        "title": post.get("title") or "",
        "flair": post.get("flair"),
        "score": int(post.get("score") or 0),
        "upvote_ratio": post.get("upvote_ratio"),
        "comment_count": int(post.get("comment_count") or 0),
        "posted_at": post.get("posted_at"),
        "crosspost_parent_id": post.get("crosspost_parent_id"),
        "image_count_preview": len(post.get("images") or []),
        "discovered_via": [{"query": query, "sort": sort, "t": time_range}],
        "request_id": request_id,
        "discovered_at": utc_now_iso(),
    }


def scrape_search_with_pagination(
    client: ContextDev,
    tracker: RunTracker,
    *,
    search_url: str,
    initial_limit: int,
    max_limit: int,
    paginate_if_has_more: bool,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], str | None]:
    """Execute reddit-search scrape; optionally increase limit if has_more is True."""
    current_limit = max(1, min(1000, initial_limit))
    cap_limit = max(current_limit, min(1000, max_limit))
    posts: list[dict[str, Any]] = []
    last_request_id: str | None = None

    while True:
        tracker.check_budget(1)
        try:
            page = client.web.scrape(
                url=search_url,
                formats={"parse": True},
                parse_params={
                    "type": "prebuilt",
                    "parser": "reddit-search",
                    "limit": current_limit,
                },
                tags=["failed-print-eval", "s1-discover"],
            )
        except ContextDevError as exc:
            tracker.handle_sdk_error(exc, operation="reddit-search", target=search_url)
            return posts, last_request_id

        last_request_id, _ = tracker.record_response(page, operation="reddit-search", target=search_url)

        if not page.parsed.success or not isinstance(page.parsed.data, dict):
            logger.warning(
                "[discover] Parse unsuccessful for %s | request_id=%s | error_code=%s | message=%s",
                search_url,
                page.request_id,
                page.parsed.error_code,
                page.parsed.message,
            )
            return posts, last_request_id

        raw_posts = page.parsed.data.get("posts") or []
        if isinstance(raw_posts, list):
            posts = [p for p in raw_posts if isinstance(p, dict)]

        has_more = bool(page.parsed.data.get("has_more"))
        if not paginate_if_has_more or not has_more or current_limit >= cap_limit:
            break

        next_limit = min(cap_limit, current_limit * 3)
        if next_limit <= current_limit:
            break
        logger.info(
            "[discover] has_more=True for %s (got %d posts at limit=%d); stepping limit to %d",
            search_url,
            len(posts),
            current_limit,
            next_limit,
        )
        current_limit = next_limit

    return posts, last_request_id


def run_discovery(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    client: ContextDev | None = None,
    subreddits_override: list[str] | None = None,
    max_queries: int | None = None,
    limit_override: int | None = None,
    max_candidates: int | None = None,
    include_recent_pass: bool = False,
    paginate_override: bool | None = None,
    reset: bool = False,
    max_requests_override: int | None = None,
) -> dict[str, Any]:
    """Run S1 discovery across configured subreddits and queries, writing candidates.jsonl."""
    logger = logging.getLogger("failed_print_eval")
    own_client = client is None
    if client is None:
        client = init_context_client(config)

    max_requests = int(
        max_requests_override
        if max_requests_override is not None
        else config.get("cost_control", {}).get("max_requests_per_run", 250)
    )
    tracker = RunTracker(stage="discover", max_requests=max_requests, data_dir=data_dir, logger=logger)

    candidates_path = data_dir / "candidates.jsonl"
    existing_rows = [] if reset else read_jsonl(candidates_path)
    candidates_by_id: dict[str, dict[str, Any]] = {
        str(row["id"]): row for row in existing_rows if "id" in row
    }
    initial_count = len(candidates_by_id)

    disc_cfg = config.get("discovery", {})
    filter_cfg = disc_cfg.get("filters", {})
    allowed_types = set(filter_cfg.get("allowed_post_types", ["image", "gallery"]))
    min_comments = int(filter_cfg.get("min_comment_count", 5))
    min_score = int(filter_cfg.get("min_score", 10))
    drop_nsfw = bool(filter_cfg.get("drop_nsfw", True))
    drop_removed = bool(filter_cfg.get("drop_removed", True))
    excluded_flairs = {str(f).strip().lower() for f in filter_cfg.get("excluded_flairs", []) if f}
    # Drop any previously saved candidates matching newly excluded flairs
    candidates_by_id = {
        cid: row
        for cid, row in candidates_by_id.items()
        if str(row.get("flair") or "").strip().lower() not in excluded_flairs
    }

    per_query_limit = int(limit_override if limit_override is not None else disc_cfg.get("limit", 100))
    max_limit = int(disc_cfg.get("max_limit", 1000))
    paginate = (
        paginate_override
        if paginate_override is not None
        else bool(disc_cfg.get("paginate_if_has_more", False))
    )

    passes_cfg = disc_cfg.get("passes", [{"sort": "top", "time": "all", "enabled": True}])
    active_passes: list[dict[str, str]] = []
    for p in passes_cfg:
        if p.get("enabled", True) or (include_recent_pass and p.get("sort") == "new"):
            active_passes.append({"sort": str(p.get("sort", "top")), "time": str(p.get("time", "all"))})
    if include_recent_pass and not any(p["sort"] == "new" for p in active_passes):
        active_passes.append({"sort": "new", "time": "year"})

    sub_cfgs = config.get("subreddits", [])
    if subreddits_override:
        wanted = {s.lower() for s in subreddits_override}
        selected_subs = [s for s in sub_cfgs if str(s.get("name", "")).lower() in wanted]
        # Allow ad-hoc subreddit names passed via CLI even if absent from config
        known_names = {str(s.get("name", "")).lower() for s in selected_subs}
        for name in subreddits_override:
            if name.lower() not in known_names:
                selected_subs.append({"name": name, "enabled": True, "flair_filter": None})
    else:
        selected_subs = [s for s in sub_cfgs if s.get("enabled", True)]

    queries: list[str] = list(config.get("queries", []))
    if max_queries is not None:
        queries = queries[:max_queries]

    total_seen = 0
    rejected_counts: dict[str, int] = {}
    stop_early = False

    try:
        for sub_entry in selected_subs:
            if stop_early:
                break
            sub_name = str(sub_entry["name"])
            flair_filter = sub_entry.get("flair_filter")
            for pass_spec in active_passes:
                if stop_early:
                    break
                sort = pass_spec["sort"]
                time_range = pass_spec["time"]
                for query in queries:
                    if max_candidates is not None and len(candidates_by_id) >= max_candidates:
                        logger.info(
                            "[discover] Reached max_candidates=%d; stopping discovery early.",
                            max_candidates,
                        )
                        stop_early = True
                        break

                    search_url = build_reddit_search_url(
                        sub_name,
                        query,
                        sort=sort,
                        time_range=time_range,
                        flair_filter=flair_filter,
                    )
                    try:
                        posts, req_id = scrape_search_with_pagination(
                            client,
                            tracker,
                            search_url=search_url,
                            initial_limit=per_query_limit,
                            max_limit=max_limit,
                            paginate_if_has_more=paginate,
                            logger=logger,
                        )
                    except BudgetExceededError as exc:
                        logger.warning("%s", exc)
                        stop_early = True
                        break

                    accepted_this_query = 0
                    for post in posts:
                        total_seen += 1
                        ok, reason = filter_search_post(
                            post,
                            allowed_types=allowed_types,
                            min_comment_count=min_comments,
                            min_score=min_score,
                            drop_nsfw=drop_nsfw,
                            drop_removed=drop_removed,
                            flair_filter=flair_filter,
                            excluded_flairs=excluded_flairs,
                        )
                        if not ok:
                            bucket = (reason or "rejected").split(":", 1)[0]
                            rejected_counts[bucket] = rejected_counts.get(bucket, 0) + 1
                            continue

                        post_id = str(post["id"])
                        via_entry = {"query": query, "sort": sort, "t": time_range}
                        if post_id in candidates_by_id:
                            via_list = candidates_by_id[post_id].setdefault("discovered_via", [])
                            if via_entry not in via_list:
                                via_list.append(via_entry)
                        else:
                            candidates_by_id[post_id] = candidate_from_post(
                                post,
                                fallback_subreddit=sub_name,
                                query=query,
                                sort=sort,
                                time_range=time_range,
                                request_id=req_id,
                            )
                            accepted_this_query += 1
                            if max_candidates is not None and len(candidates_by_id) >= max_candidates:
                                break

                    logger.info(
                        "[discover] r/%s q=%r (%s/%s) -> raw=%d, new_unique=%d, total_unique=%d",
                        sub_name,
                        query,
                        sort,
                        time_range,
                        len(posts),
                        accepted_this_query,
                        len(candidates_by_id),
                    )
    finally:
        if own_client:
            client.close()

    def _rank_key(row: dict[str, Any]) -> tuple[int, int, int]:
        flair_l = str(row.get("flair") or "").lower()
        is_solved_flair = 1 if ("solved" in flair_l and "unsolved" not in flair_l) or "print fixed" in flair_l else 0
        is_troubleshoot_flair = 1 if flair_l in {"fix my print", "troubleshooting", "print fixed", "solved", "solved!"} else 0
        return (is_solved_flair, is_troubleshoot_flair, int(row.get("comment_count") or 0))

    # Interleave candidates round-robin across primary discovery queries for diverse taxonomy coverage
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in candidates_by_id.values():
        via = row.get("discovered_via") or []
        primary_q = str(via[0].get("query") if via and isinstance(via[0], dict) else "other")
        buckets.setdefault(primary_q, []).append(row)
    for q_list in buckets.values():
        q_list.sort(key=_rank_key, reverse=True)

    ordered_candidates: list[dict[str, Any]] = []
    bucket_keys = list(buckets.keys())
    idx = 0
    while True:
        added = False
        for qk in bucket_keys:
            if idx < len(buckets[qk]):
                ordered_candidates.append(buckets[qk][idx])
                added = True
        if not added:
            break
        idx += 1

    write_jsonl(candidates_path, ordered_candidates)
    run_summary = tracker.log_summary()
    run_summary.update(
        {
            "initial_candidates": initial_count,
            "new_candidates": len(ordered_candidates) - initial_count,
            "total_candidates": len(ordered_candidates),
            "raw_posts_inspected": total_seen,
            "rejected_counts": rejected_counts,
            "candidates_path": str(candidates_path),
        }
    )
    return run_summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S1: Discover candidate troubleshooting posts on Reddit.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument("--subreddits", nargs="+", default=None, help="Override subreddit names")
    parser.add_argument("--max-queries", type=int, default=None, help="Limit number of seed queries per subreddit")
    parser.add_argument("--limit", type=int, default=None, help="Per-query reddit-search limit (1..1000)")
    parser.add_argument("--max-candidates", type=int, default=None, help="Stop once N unique candidates exist")
    parser.add_argument("--include-recent-pass", action="store_true", help="Also run sort=new, t=year pass")
    parser.add_argument("--paginate", action="store_true", help="Increase limit when has_more is true")
    parser.add_argument("--reset", action="store_true", help="Ignore existing candidates.jsonl")
    parser.add_argument("--max-requests", type=int, default=None, help="Override max_requests_per_run")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_discovery(
        config,
        data_dir=args.data_dir,
        subreddits_override=args.subreddits,
        max_queries=args.max_queries,
        limit_override=args.limit,
        max_candidates=args.max_candidates,
        include_recent_pass=args.include_recent_pass,
        paginate_override=True if args.paginate else None,
        reset=args.reset,
        max_requests_override=args.max_requests,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
