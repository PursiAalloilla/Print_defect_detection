"""Stage S4: Download accepted failure images via Context.dev bytes format and record SHA-256 assets."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any

from context.dev import ContextDev, ContextDevError

from src.common import (
    BudgetExceededError,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    RunTracker,
    init_context_client,
    load_config,
    parse_image_dimensions,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_jsonl,
)

_CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/avif": "avif",
    "image/tiff": "tiff",
}


def extension_from_content_type(content_type: str) -> str:
    """Derive clean file extension from an image/* MIME content-type."""
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _CONTENT_TYPE_TO_EXT:
        return _CONTENT_TYPE_TO_EXT[mime]
    if "/" in mime:
        subtype = mime.split("/", 1)[1].split("+", 1)[0]
        cleaned = re.sub(r"[^a-z0-9]+", "", subtype)
        if cleaned:
            return cleaned
    return "img"


def _save_bytes_payload(
    bytes_block: Any,
    *,
    image_url: str,
    out_dir: Path,
    record_id: str,
    post_id: str,
    subreddit: str,
    comment_count: int,
    image_index: int,
    expected_width: int | None,
    expected_height: int | None,
    req_id: str | None,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """Validate an image/* Bytes response block, write image file, and return asset metadata."""
    if bytes_block is None or not getattr(bytes_block, "success", False) or getattr(bytes_block, "data", None) is None:
        logger.warning(
            "[download] Bytes output failed for %s | request_id=%s | error_code=%s | message=%s",
            image_url,
            req_id,
            getattr(bytes_block, "error_code", None),
            getattr(bytes_block, "message", None),
        )
        return None

    content_type = (bytes_block.data.content_type or "").strip()
    if not content_type.lower().startswith("image/"):
        logger.warning(
            "[download] Rejecting non-image contentType=%r for %s | request_id=%s",
            content_type,
            image_url,
            req_id,
        )
        return None

    try:
        raw_bytes = base64.b64decode(bytes_block.data.base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        logger.warning(
            "[download] Invalid base64 payload for %s | request_id=%s | err=%s",
            image_url,
            req_id,
            exc,
        )
        return None

    if not raw_bytes:
        logger.warning("[download] Empty decoded image bytes for %s | request_id=%s", image_url, req_id)
        return None

    ext = extension_from_content_type(content_type)
    filename = f"{record_id}_{image_index}.{ext}"
    out_dir.mkdir(parents=True, exist_ok=True)
    full_path = out_dir / filename
    full_path.write_bytes(raw_bytes)

    parsed_w, parsed_h = parse_image_dimensions(raw_bytes)
    width = int(parsed_w or expected_width or 0)
    height = int(parsed_h or expected_height or 0)
    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()

    return {
        "record_id": record_id,
        "post_id": post_id,
        "subreddit": subreddit,
        "comment_count": comment_count,
        "image_index": image_index,
        "path": f"images/{filename}",
        "source_url": image_url,
        "content_type": content_type.split(";", 1)[0].strip().lower(),
        "width": width,
        "height": height,
        "sha256": sha256_hex,
        "size_bytes": len(raw_bytes),
        "retrieved_at": utc_now_iso(),
        "request_id": req_id,
    }


def download_single_image(
    client: ContextDev,
    tracker: RunTracker,
    *,
    image_url: str,
    out_dir: Path,
    record_id: str,
    post_id: str,
    subreddit: str,
    comment_count: int,
    image_index: int,
    expected_width: int | None,
    expected_height: int | None,
    timeout_ms: int = 30000,
    max_age_ms: int = 0,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """Download one image URL via Context.dev formats.bytes, verify MIME & base64, and write to disk."""
    tracker.check_budget(1)
    try:
        page = client.web.scrape(
            url=image_url,
            formats={"bytes": True},
            max_age_ms=max_age_ms,
            timeout_opts={"milliseconds": timeout_ms, "behavior": "fail"},
            tags=["failed-print-eval", "s4-download"],
        )
    except ContextDevError as exc:
        tracker.handle_sdk_error(exc, operation="bytes-download", target=image_url)
        return None

    req_id, _ = tracker.record_response(page, operation="bytes-download", target=image_url)
    return _save_bytes_payload(
        page.bytes,
        image_url=image_url,
        out_dir=out_dir,
        record_id=record_id,
        post_id=post_id,
        subreddit=subreddit,
        comment_count=comment_count,
        image_index=image_index,
        expected_width=expected_width,
        expected_height=expected_height,
        req_id=req_id,
        logger=logger,
    )


def _download_images_via_batch(
    client: ContextDev,
    tracker: RunTracker,
    *,
    tasks: list[dict[str, Any]],
    out_dir: Path,
    timeout_ms: int,
    max_age_ms: int,
    poll_interval_sec: float,
    max_wait_sec: float,
    logger: logging.Logger,
) -> tuple[dict[tuple[str, int], dict[str, Any]], int]:
    """Download multiple image URLs asynchronously via Context.dev Batches (formats.bytes)."""
    tracker.check_budget(len(tasks))
    task_map = {f"{t['record_id']}:{t['image_index']}": t for t in tasks}
    digest = hashlib.sha256(
        "|".join(sorted(task_map.keys())).encode("utf-8")
    ).hexdigest()[:40]
    idem_key = f"fpe-s4-bytes-{len(tasks)}-{digest}"

    urls_payload = [
        {
            "url": t["image_url"],
            "item_id": f"{t['record_id']}:{t['image_index']}",
        }
        for t in tasks
    ]
    submit_client = client.with_options(max_retries=0)
    batch_sub = submit_client.batch.submit(
        input={
            "mode": "scrape",
            "data": {
                "formats": {"bytes": True},
                "max_age_ms": max_age_ms,
                "timeout_opts": {"milliseconds": timeout_ms, "behavior": "fail"},
                "urls": urls_payload,
            },
        },
        idempotency_key=idem_key,
        tags=["failed-print-eval", "s4-download-batch"],
    )
    tracker.record_response(batch_sub, operation="batch.submit", target=batch_sub.id)
    batch_id = batch_sub.id
    logger.info(
        "[download] Submitted bytes batch_id=%s | submitted=%s reserved=%s credits_reserved=%s",
        batch_id,
        getattr(batch_sub.input, "submitted", None),
        getattr(batch_sub.input, "reserved", None),
        getattr(batch_sub.credits, "reserved", None),
    )

    deadline = time.monotonic() + max_wait_sec
    while True:
        st = client.batch.retrieve(batch_id)
        tracker.record_response(st, operation="batch.retrieve", target=batch_id)
        prog = st.progress
        logger.info(
            "[download] Batch %s status=%s | succeeded=%s failed=%s pending=%s",
            batch_id,
            st.status,
            getattr(prog, "succeeded", None),
            getattr(prog, "failed", None),
            getattr(prog, "pending", None),
        )
        if st.status in {"completed", "cancelled", "failed"}:
            final_st = st
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Image batch {batch_id} timed out after {max_wait_sec}s")
        time.sleep(poll_interval_sec)

    net_credits = int(getattr(final_st.credits, "net", None) or getattr(final_st.credits, "reserved", 0) or 0)
    tracker.credits_consumed += net_credits

    saved: dict[tuple[str, int], dict[str, Any]] = {}
    rejected = 0
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"limit": 100}
        if cursor:
            kwargs["cursor"] = cursor
        res_page = client.batch.get_results(batch_id, **kwargs)
        tracker.record_response(res_page, operation="batch.get_results", target=batch_id)
        for rec in res_page.data or []:
            item_id = getattr(rec, "item_id", None) or ""
            t = task_map.get(item_id)
            if t is None or rec.status != "ok":
                rejected += 1
                continue
            asset = _save_bytes_payload(
                rec.result.bytes,
                image_url=t["image_url"],
                out_dir=out_dir,
                record_id=t["record_id"],
                post_id=t["post_id"],
                subreddit=t["subreddit"],
                comment_count=t["comment_count"],
                image_index=t["image_index"],
                expected_width=t["expected_width"],
                expected_height=t["expected_height"],
                req_id=rec.result.request_id,
                logger=logger,
            )
            if asset is None:
                rejected += 1
            else:
                saved[(t["record_id"], t["image_index"])] = asset
        if not res_page.has_more or not res_page.next_cursor:
            break
        cursor = res_page.next_cursor
    return saved, rejected


def run_download(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    client: ContextDev | None = None,
    max_posts: int | None = None,
    max_images_per_post_override: int | None = None,
    force_batch: bool = False,
    overwrite: bool = False,
    max_requests_override: int | None = None,
) -> dict[str, Any]:
    """Run S4 image download over filtered_threads.jsonl and emit assets.jsonl."""
    logger = logging.getLogger("failed_print_eval")
    own_client = client is None
    if client is None:
        client = init_context_client(config)

    max_requests = int(
        max_requests_override
        if max_requests_override is not None
        else config.get("cost_control", {}).get("max_requests_per_run", 250)
    )
    tracker = RunTracker(stage="download", max_requests=max_requests, data_dir=data_dir, logger=logger)

    dl_cfg = config.get("download", {})
    timeout_ms = int(dl_cfg.get("timeout_ms", 30000))
    max_age_ms = int(dl_cfg.get("max_age_ms", 0))
    max_per_post = (
        max_images_per_post_override
        if max_images_per_post_override is not None
        else dl_cfg.get("max_images_per_post")
    )

    filtered_threads = read_jsonl(data_dir / "filtered_threads.jsonl")
    if max_posts is not None:
        filtered_threads = filtered_threads[:max_posts]

    assets_path = data_dir / "assets.jsonl"
    images_dir = data_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    existing_assets = [] if overwrite else read_jsonl(assets_path)
    assets_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in existing_assets:
        rel_path = str(row.get("path") or "")
        if rel_path and (data_dir / rel_path).is_file():
            key = (str(row.get("record_id")), int(row.get("image_index", 0)))
            assets_by_key[key] = row

    downloaded = 0
    skipped = 0
    rejected = 0

    tasks: list[dict[str, Any]] = []
    for thread in filtered_threads:
        record_id = str(thread["record_id"])
        post_id = str(thread["post_id"])
        subreddit = str(thread["subreddit"])
        comment_count = int(thread.get("comment_count") or 0)
        images = list(thread.get("accepted_images") or [])
        if max_per_post is not None:
            images = images[: int(max_per_post)]

        for idx, img in enumerate(images):
            key = (record_id, idx)
            if key in assets_by_key and not overwrite:
                skipped += 1
                continue
            img_url = str(img.get("url") or "").strip()
            if not img_url:
                rejected += 1
                continue
            tasks.append(
                {
                    "record_id": record_id,
                    "post_id": post_id,
                    "subreddit": subreddit,
                    "comment_count": comment_count,
                    "image_index": idx,
                    "image_url": img_url,
                    "expected_width": img.get("width"),
                    "expected_height": img.get("height"),
                }
            )

    fetch_cfg = config.get("fetch", {})
    batch_threshold = int(fetch_cfg.get("batch_threshold", 200))
    use_batch = bool(force_batch or len(tasks) > batch_threshold)

    try:
        if tasks and use_batch:
            batch_saved, batch_rej = _download_images_via_batch(
                client,
                tracker,
                tasks=tasks,
                out_dir=images_dir,
                timeout_ms=timeout_ms,
                max_age_ms=max_age_ms,
                poll_interval_sec=float(fetch_cfg.get("batch_poll_interval_sec", 15.0)),
                max_wait_sec=float(fetch_cfg.get("batch_max_wait_sec", 1800.0)),
                logger=logger,
            )
            assets_by_key.update(batch_saved)
            downloaded += len(batch_saved)
            rejected += batch_rej
        else:
            for t in tasks:
                try:
                    asset = download_single_image(
                        client,
                        tracker,
                        image_url=t["image_url"],
                        out_dir=images_dir,
                        record_id=t["record_id"],
                        post_id=t["post_id"],
                        subreddit=t["subreddit"],
                        comment_count=t["comment_count"],
                        image_index=t["image_index"],
                        expected_width=t["expected_width"],
                        expected_height=t["expected_height"],
                        timeout_ms=timeout_ms,
                        max_age_ms=max_age_ms,
                        logger=logger,
                    )
                except BudgetExceededError as exc:
                    logger.warning("%s", exc)
                    break

                if asset is None:
                    rejected += 1
                else:
                    assets_by_key[(t["record_id"], t["image_index"])] = asset
                    downloaded += 1
    finally:
        if own_client:
            client.close()

    ordered_assets = [
        assets_by_key[k] for k in sorted(assets_by_key.keys(), key=lambda pair: (pair[0], pair[1]))
    ]
    write_jsonl(assets_path, ordered_assets)

    posts_with_images = len({row["record_id"] for row in ordered_assets})
    summary = tracker.log_summary()
    summary.update(
        {
            "downloaded": downloaded,
            "skipped_existing": skipped,
            "rejected": rejected,
            "total_assets": len(ordered_assets),
            "posts_with_images": posts_with_images,
            "assets_path": str(assets_path),
        }
    )
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S4: Download failure images via Context.dev bytes format.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument("--max-posts", type=int, default=None, help="Limit number of filtered posts processed")
    parser.add_argument("--max-images-per-post", type=int, default=None, help="Max images downloaded per post")
    parser.add_argument("--batch", action="store_true", help="Use Context.dev Batches for image bytes downloads")
    parser.add_argument("--overwrite", action="store_true", help="Re-download existing images")
    parser.add_argument("--max-requests", type=int, default=None, help="Override max_requests_per_run")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_download(
        config,
        data_dir=args.data_dir,
        max_posts=args.max_posts,
        max_images_per_post_override=args.max_images_per_post,
        force_batch=args.batch,
        overwrite=args.overwrite,
        max_requests_override=args.max_requests,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
