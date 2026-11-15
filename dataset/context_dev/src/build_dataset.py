"""Stage S6: Assemble validated evaluation dataset (eval.jsonl + 10% val.jsonl holdout) with SHA-256 crosspost dedupe."""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.common import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_SCHEMA_DIR,
    RunTracker,
    init_context_client,
    init_llm_client,
    load_config,
    make_record_id,
    read_json,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_jsonl,
)
from src.discover import build_reddit_search_url
from src.download import _download_images_via_batch
from src.filter import unwrap_raw_thread
from src.synthesize import verify_clean_print_in_isolation


def assign_split(record_id: str, *, val_ratio: float = 0.10, seed: int = 42, final_release: bool = False) -> str:
    """Deterministically assign a record to 'val' (holdout) or 'test'."""
    if final_release or val_ratio <= 0.0:
        return "test"
    digest = hashlib.sha256(f"{seed}:{record_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return "val" if bucket < val_ratio else "test"


def dedupe_crossposts_by_sha256(
    candidates: list[dict[str, Any]],
    assets_by_record: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate crossposted failures sharing image sha256, keeping highest comment_count thread."""
    ordered = sorted(
        candidates,
        key=lambda r: (
            int(r.get("comment_count") or 0),
            int(r.get("score") or 0),
            str(r.get("record_id") or ""),
        ),
        reverse=True,
    )
    claimed_hashes: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for row in ordered:
        rec_id = str(row["record_id"])
        rec_assets = assets_by_record.get(rec_id, [])
        hashes = [str(a["sha256"]) for a in rec_assets if a.get("sha256")]
        if not hashes:
            continue

        conflicting_owner = next((claimed_hashes[h] for h in hashes if h in claimed_hashes), None)
        if conflicting_owner is not None:
            dropped.append(
                {
                    "record_id": rec_id,
                    "duplicate_of": conflicting_owner,
                    "comment_count": row.get("comment_count"),
                }
            )
            continue

        for h in hashes:
            claimed_hashes[h] = rec_id
        kept.append(row)

    return kept, dropped


def _format_image_entry(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(asset["path"]),
        "sha256": str(asset["sha256"]),
        "width": max(1, int(asset.get("width") or 1)),
        "height": max(1, int(asset.get("height") or 1)),
    }


def build_records_for_post(
    filtered_row: dict[str, Any],
    raw_thread: dict[str, Any],
    assets: list[dict[str, Any]],
    synthesis_wrapper: dict[str, Any],
    *,
    body_excerpt_max_chars: int = 1000,
    val_ratio: float = 0.10,
    split_seed: int = 42,
    final_release: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Construct (positive_defect_records, negative_clean_records) for an accepted post."""
    thread = unwrap_raw_thread(raw_thread)
    post = thread["post"]
    synth = synthesis_wrapper.get("synthesis", synthesis_wrapper)

    record_id = str(filtered_row["record_id"])
    subreddit = str(post.get("subreddit") or filtered_row.get("subreddit") or "FixMyPrint")
    url = str(post.get("url") or filtered_row.get("url") or "")
    retrieved_at = str(filtered_row.get("retrieved_at") or utc_now_iso())

    raw_body = str(post.get("body") or "").strip()
    body_excerpt = raw_body[:body_excerpt_max_chars]

    # Deduplicate identical image hashes within the same post while preserving order
    unique_assets: list[dict[str, Any]] = []
    seen_local_sha: set[str] = set()
    for a in sorted(assets, key=lambda x: int(x.get("image_index", 0))):
        sha = str(a.get("sha256") or "")
        if sha and sha not in seen_local_sha:
            seen_local_sha.add(sha)
            unique_assets.append(a)

    if not unique_assets:
        return [], []

    upvote_ratio = post.get("upvote_ratio")
    if upvote_ratio is None:
        upvote_ratio = filtered_row.get("upvote_ratio")
    if upvote_ratio is not None:
        upvote_ratio = round(float(upvote_ratio), 4)

    quality_block = {
        "min_comment_score": int(filtered_row.get("min_comment_score") or 0),
        "comment_count": int(post.get("comment_count") or filtered_row.get("comment_count") or 0),
        "upvote_ratio": upvote_ratio,
    }
    source_block = {
        "platform": "reddit",
        "subreddit": subreddit,
        "url": url,
        "retrieved_at": retrieved_at,
    }
    context_block = {
        "title": str(post.get("title") or filtered_row.get("title") or ""),
        "body_excerpt": body_excerpt,
        "printer_context": synth.get("printer_context"),
    }

    # Apply visual image_roles gating if produced by multimodal S5
    role_by_idx: dict[int, str] = {}
    for entry in synth.get("image_roles") or []:
        if isinstance(entry, dict) and "image_index" in entry and "role" in entry:
            role_by_idx[int(entry["image_index"])] = str(entry["role"])

    clean_negative_records: list[dict[str, Any]] = []
    if role_by_idx:
        failed_assets = [
            a for a in unique_assets if role_by_idx.get(int(a.get("image_index", 0)), "failed_print") == "failed_print"
        ]
        clean_assets = [
            a for a in unique_assets if role_by_idx.get(int(a.get("image_index", 0))) == "clean_print"
        ]
        # Enforce post-level independence: emit at most 1 negative-control image per source thread
        for c_asset in clean_assets[:1]:
            c_idx = int(c_asset.get("image_index", 0))
            clean_negative_records.append(
                {
                    "id": f"{record_id}_clean_{c_idx}",
                    "source": source_block,
                    "context": context_block,
                    "images": [_format_image_entry(c_asset)],
                    "reference": {
                        "defect_class": "clean",
                        "likely_causes": [],
                        "recommended_fixes": [],
                        "community_consensus": "Clean or post-fix 3D print photograph with no visible print defect.",
                        "confidence": "high",
                        "solved": True,
                    },
                    "quality": quality_block,
                    "splits": "test",
                }
            )
    else:
        failed_assets = unique_assets

    if synth.get("shows_failed_print") is False or not failed_assets:
        return [], clean_negative_records

    solved_flag = bool(synth.get("solved") or str(filtered_row.get("solved_source") or "").startswith("flair:"))
    gallery_split = bool(synth.get("gallery_split", False))
    gallery_items = synth.get("gallery_items")

    failed_by_idx = {int(a.get("image_index", i)): a for i, a in enumerate(failed_assets)}

    if gallery_split and isinstance(gallery_items, list) and gallery_items:
        emitted: list[dict[str, Any]] = []
        for g_item in gallery_items:
            if not isinstance(g_item, dict) or not bool(g_item.get("include_in_eval", True)):
                continue
            img_idx = int(g_item.get("image_index", -1))
            matched_asset = failed_by_idx.get(img_idx)
            if matched_asset is None:
                continue
            sub_id = f"{record_id}_g{img_idx}"
            split_label = assign_split(
                sub_id, val_ratio=val_ratio, seed=split_seed, final_release=final_release
            )
            ref_block: dict[str, Any] = {
                "defect_class": g_item["defect_class"],
                "likely_causes": list(g_item.get("likely_causes") or [])[:5],
                "recommended_fixes": list(g_item.get("recommended_fixes") or [])[:5],
                "community_consensus": str(synth["community_consensus"]),
                "confidence": str(synth["confidence"]),
                "solved": solved_flag,
                "gallery_split": True,
            }
            if g_item.get("defect_class_free") is not None:
                ref_block["defect_class_free"] = g_item["defect_class_free"]
            if synth.get("evidence_comment_ids"):
                ref_block["evidence_comment_ids"] = list(synth["evidence_comment_ids"])

            emitted.append(
                {
                    "id": sub_id,
                    "source": source_block,
                    "context": context_block,
                    "images": [_format_image_entry(matched_asset)],
                    "reference": ref_block,
                    "quality": quality_block,
                    "splits": split_label,
                }
            )
        if emitted:
            return emitted, clean_negative_records

    split_label = assign_split(
        record_id, val_ratio=val_ratio, seed=split_seed, final_release=final_release
    )
    ref_obj: dict[str, Any] = {
        "defect_class": str(synth["defect_class"]),
        "likely_causes": list(synth.get("likely_causes") or [])[:5],
        "recommended_fixes": list(synth.get("recommended_fixes") or [])[:5],
        "community_consensus": str(synth["community_consensus"]),
        "confidence": str(synth["confidence"]),
        "solved": solved_flag,
    }
    if synth.get("defect_class_free") is not None:
        ref_obj["defect_class_free"] = synth["defect_class_free"]
    if synth.get("evidence_comment_ids") is not None:
        ref_obj["evidence_comment_ids"] = list(synth["evidence_comment_ids"])
    if gallery_split:
        ref_obj["gallery_split"] = True

    return (
        [
            {
                "id": record_id,
                "source": source_block,
                "context": context_block,
                "images": [_format_image_entry(a) for a in failed_assets],
                "reference": ref_obj,
                "quality": quality_block,
                "splits": split_label,
            }
        ],
        clean_negative_records,
    )


def _fetch_and_verify_clean_onbed_controls(
    config: dict[str, Any],
    *,
    data_dir: Path,
    target_total: int,
    existing_records: list[dict[str, Any]],
    validator: Draft202012Validator,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """Fetch clean on-bed / finished 3D print photos from r/3Dprinting via Context.dev and verify in visual isolation."""
    if len(existing_records) >= target_total:
        return []

    needed = target_total - len(existing_records)
    existing_posts = {r["id"].split("_clean_")[0] for r in existing_records}
    existing_shas = {im["sha256"] for r in existing_records for im in r["images"]}

    # Also check already-downloaded cleanprint_* assets on disk first so re-runs cost 0 Context.dev credits
    all_assets = read_jsonl(data_dir / "assets.jsonl")
    cached_clean = [a for a in all_assets if str(a.get("record_id", "")).startswith("3dprinting_")]

    synth_cfg = config.get("synthesis", {})
    llm_client = init_llm_client(
        str(synth_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"))
    )
    v_model = str(synth_cfg.get("model", "gemini-3.5-flash"))

    added: list[dict[str, Any]] = []

    def _try_accept_asset(asset: dict[str, Any], title: str, post_url: str, score_val: int, comments_val: int, ratio_val: Any) -> bool:
        rec_id = str(asset["record_id"])
        sha = str(asset.get("sha256") or "")
        img_p = data_dir / str(asset["path"])
        if rec_id in existing_posts or not sha or sha in existing_shas or not img_p.is_file():
            return False
        if not verify_clean_print_in_isolation(llm_client, model=v_model, image_path=img_p):
            return False
        nrec = {
            "id": f"{rec_id}_clean_0",
            "source": {
                "platform": "reddit",
                "subreddit": "3Dprinting",
                "url": post_url,
                "retrieved_at": str(asset.get("retrieved_at") or utc_now_iso()),
            },
            "context": {
                "title": title or "Clean 3D print",
                "body_excerpt": "",
                "printer_context": None,
            },
            "images": [_format_image_entry(asset)],
            "reference": {
                "defect_class": "clean",
                "likely_causes": [],
                "recommended_fixes": [],
                "community_consensus": "Clean completed 3D print verified defect-free in visual isolation.",
                "confidence": "high",
                "solved": True,
            },
            "quality": {
                "min_comment_score": 1,
                "comment_count": comments_val,
                "upvote_ratio": ratio_val,
            },
            "splits": "test",
        }
        if list(validator.iter_errors(nrec)):
            return False
        added.append(nrec)
        existing_posts.add(rec_id)
        existing_shas.add(sha)
        return True

    for ca in cached_clean:
        if len(existing_records) + len(added) >= target_total:
            return added
        _try_accept_asset(
            ca,
            title="Clean 3D print control",
            post_url=f"https://www.reddit.com/r/3Dprinting/comments/{ca['post_id']}/",
            score_val=50,
            comments_val=int(ca.get("comment_count") or 10),
            ratio_val=0.95,
        )

    still_needed = target_total - (len(existing_records) + len(added))
    if still_needed <= 0:
        return added

    c_client = init_context_client(config)
    tracker = RunTracker(stage="clean_controls", max_requests=60, data_dir=data_dir, logger=logger)
    cand_posts: dict[str, dict[str, Any]] = {}
    clean_queries = [
        "first layer porn",
        "fresh off the print bed",
        "clean benchy",
    ]
    bad_kw = ("fail", "help", "wrong", "spaghetti", "warp", "shift", "blob", "stringing", "clog", "issue", "broken")

    try:
        for q in clean_queries:
            if len(cand_posts) >= still_needed * 2:
                break
            s_url = build_reddit_search_url("3Dprinting", q, sort="top", time_range="all")
            page = c_client.web.scrape(
                url=s_url,
                formats={"parse": True},
                parse_params={"type": "prebuilt", "parser": "reddit-search", "limit": 60},
                tags=["failed-print-eval", "clean-controls-discover"],
            )
            tracker.record_response(page, operation="reddit-search-clean", target=s_url)
            if not page.parsed.success or not isinstance(page.parsed.data, dict):
                continue
            for p in page.parsed.data.get("posts") or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "")
                rid = make_record_id("3Dprinting", pid)
                if not pid or rid in existing_posts or rid in cand_posts:
                    continue
                if p.get("type") not in {"image", "gallery"} or p.get("is_nsfw") or p.get("removed_by") is not None:
                    continue
                title_l = str(p.get("title") or "").lower()
                if any(bk in title_l for bk in bad_kw):
                    continue
                imgs = [
                    im for im in (p.get("images") or [])
                    if isinstance(im, dict)
                    and str(im.get("url") or "").startswith("https://")
                    and int(im.get("width") or 0) >= 600
                    and int(im.get("height") or 0) >= 450
                ]
                if not imgs or int(p.get("score") or 0) < 25:
                    continue
                cand_posts[rid] = {"post": p, "img": imgs[0], "record_id": rid, "post_id": pid}
                if len(cand_posts) >= max(24, still_needed * 2):
                    break

        tasks = [
            {
                "record_id": info["record_id"],
                "post_id": info["post_id"],
                "subreddit": "3Dprinting",
                "comment_count": int(info["post"].get("comment_count") or 0),
                "image_index": 0,
                "image_url": str(info["img"]["url"]),
                "expected_width": int(info["img"]["width"]),
                "expected_height": int(info["img"]["height"]),
            }
            for info in cand_posts.values()
        ]
        if tasks:
            dl_saved, _ = _download_images_via_batch(
                c_client,
                tracker,
                tasks=tasks,
                out_dir=data_dir / "images",
                timeout_ms=30000,
                max_age_ms=0,
                poll_interval_sec=10.0,
                max_wait_sec=600.0,
                logger=logger,
            )
            # Persist newly downloaded clean assets into assets.jsonl
            assets_map = {(str(a["record_id"]), int(a.get("image_index", 0))): a for a in all_assets}
            assets_map.update(dl_saved)
            write_jsonl(
                data_dir / "assets.jsonl",
                [assets_map[k] for k in sorted(assets_map.keys())],
            )
            for (rid, _), asset in sorted(dl_saved.items()):
                if len(existing_records) + len(added) >= target_total:
                    break
                p = cand_posts[rid]["post"]
                _try_accept_asset(
                    asset,
                    title=str(p.get("title") or "Clean print"),
                    post_url=str(p.get("url") or f"https://www.reddit.com/r/3Dprinting/comments/{p.get('id')}/"),
                    score_val=int(p.get("score") or 0),
                    comments_val=int(p.get("comment_count") or 0),
                    ratio_val=p.get("upvote_ratio"),
                )
    finally:
        c_client.close()
        tracker.log_summary()

    return added


def run_build_dataset(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    schema_dir: Path = DEFAULT_SCHEMA_DIR,
    final_release: bool = False,
    val_ratio_override: float | None = None,
    harvest_showcase_negatives: bool = False,
    fetch_clean_controls_target: int = 0,
) -> dict[str, Any]:
    """Run S6 dataset assembly, validating every record against record.schema.json."""
    logger = logging.getLogger("failed_print_eval")
    ds_cfg = config.get("dataset", {})
    val_ratio = float(
        val_ratio_override if val_ratio_override is not None else ds_cfg.get("val_split_ratio", 0.10)
    )
    split_seed = int(ds_cfg.get("split_seed", 42))
    excerpt_chars = int(ds_cfg.get("body_excerpt_max_chars", 1000))

    record_schema = read_json(schema_dir / "record.schema.json")
    validator = Draft202012Validator(record_schema)

    filtered_rows = read_jsonl(data_dir / "filtered_threads.jsonl")
    all_assets = read_jsonl(data_dir / "assets.jsonl")
    assets_by_record: dict[str, list[dict[str, Any]]] = {}
    for asset in all_assets:
        rel_path = str(asset.get("path") or "")
        if rel_path and (data_dir / rel_path).is_file():
            rec_id = str(asset["record_id"])
            assets_by_record.setdefault(rec_id, []).append(asset)

    deduped_threads, crosspost_dropped = dedupe_crossposts_by_sha256(filtered_rows, assets_by_record)

    records_dir = data_dir / "records"
    dataset_dir = data_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    eval_records: list[dict[str, Any]] = []
    val_records: list[dict[str, Any]] = []
    negative_control_records: list[dict[str, Any]] = []
    excluded_non_defect: list[dict[str, Any]] = []
    missing_synthesis = 0
    missing_raw = 0
    schema_errors = 0

    for f_row in sorted(deduped_threads, key=lambda r: str(r["record_id"])):
        rec_id = str(f_row["record_id"])
        synth_path = records_dir / f"{rec_id}.json"
        if not synth_path.is_file():
            missing_synthesis += 1
            continue

        raw_rel = str(f_row.get("raw_path") or "")
        raw_path = data_dir / raw_rel
        if not raw_path.is_file():
            missing_raw += 1
            continue

        synth_data = read_json(synth_path)
        built_list, clean_neg_list = build_records_for_post(
            f_row,
            read_json(raw_path),
            assets_by_record.get(rec_id, []),
            synth_data,
            body_excerpt_max_chars=excerpt_chars,
            val_ratio=val_ratio,
            split_seed=split_seed,
            final_release=final_release,
        )

        for nrec in clean_neg_list:
            if not list(validator.iter_errors(nrec)):
                negative_control_records.append(nrec)

        if not built_list:
            synth_inner = synth_data.get("synthesis", synth_data)
            excluded_non_defect.append(
                {
                    "record_id": rec_id,
                    "shows_failed_print": synth_inner.get("shows_failed_print"),
                    "image_roles": synth_inner.get("image_roles"),
                }
            )
            continue

        for rec in built_list:
            errs = list(validator.iter_errors(rec))
            if errs:
                schema_errors += 1
                logger.error(
                    "[build_dataset] Record %s failed record.schema.json: %s",
                    rec["id"],
                    "; ".join(e.message for e in errs),
                )
                continue
            if rec["splits"] == "val":
                val_records.append(rec)
            else:
                eval_records.append(rec)

    if harvest_showcase_negatives:
        synth_cfg = config.get("synthesis", {})
        llm_client = init_llm_client(str(synth_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")))
        v_model = str(synth_cfg.get("model", "gemini-3.5-flash"))
        existing_neg_posts = {r["id"].split("_clean_")[0] for r in negative_control_records}
        existing_neg_shas = {im["sha256"] for r in negative_control_records for im in r["images"]}
        for d_row in read_jsonl(data_dir / "discarded.jsonl"):
            if "celebratory_followup_showcase" not in (d_row.get("reasons") or []):
                continue
            rec_id = str(d_row["record_id"])
            if rec_id in existing_neg_posts:
                continue
            cand_assets = sorted(assets_by_record.get(rec_id, []), key=lambda x: int(x.get("image_index", 0)))
            for c_asset in cand_assets[:1]:
                sha = str(c_asset.get("sha256") or "")
                img_p = data_dir / str(c_asset["path"])
                if not sha or sha in existing_neg_shas or not img_p.is_file():
                    continue
                if verify_clean_print_in_isolation(llm_client, model=v_model, image_path=img_p):
                    nrec = {
                        "id": f"{rec_id}_clean_{int(c_asset.get('image_index', 0))}",
                        "source": {
                            "platform": "reddit",
                            "subreddit": str(d_row.get("subreddit") or "FixMyPrint"),
                            "url": str(d_row.get("url") or ""),
                            "retrieved_at": str(d_row.get("retrieved_at") or utc_now_iso()),
                        },
                        "context": {
                            "title": str(d_row.get("title") or ""),
                            "body_excerpt": "",
                            "printer_context": None,
                        },
                        "images": [_format_image_entry(c_asset)],
                        "reference": {
                            "defect_class": "clean",
                            "likely_causes": [],
                            "recommended_fixes": [],
                            "community_consensus": "Clean completed 3D print verified defect-free in visual isolation.",
                            "confidence": "high",
                            "solved": True,
                        },
                        "quality": {
                            "min_comment_score": int(d_row.get("min_comment_score") or 0),
                            "comment_count": int(d_row.get("comment_count") or 0),
                            "upvote_ratio": d_row.get("upvote_ratio"),
                        },
                        "splits": "test",
                    }
                    if not list(validator.iter_errors(nrec)):
                        negative_control_records.append(nrec)
                        existing_neg_posts.add(rec_id)
                        existing_neg_shas.add(sha)

    if fetch_clean_controls_target > len(negative_control_records):
        extra_clean = _fetch_and_verify_clean_onbed_controls(
            config,
            data_dir=data_dir,
            target_total=fetch_clean_controls_target,
            existing_records=negative_control_records,
            validator=validator,
            logger=logger,
        )
        negative_control_records.extend(extra_clean)

    eval_path = dataset_dir / "eval.jsonl"
    val_path = dataset_dir / "val.jsonl"
    neg_path = dataset_dir / "negative_controls.jsonl"
    excl_path = dataset_dir / "excluded_non_defect.jsonl"
    write_jsonl(eval_path, eval_records)
    write_jsonl(val_path, val_records)
    write_jsonl(neg_path, negative_control_records)
    write_jsonl(excl_path, excluded_non_defect)

    all_emitted = eval_records + val_records
    multi_image_count = sum(1 for r in all_emitted if len(r["images"]) > 1)
    high_or_solved = sum(
        1
        for r in all_emitted
        if r["reference"]["solved"] or r["reference"]["confidence"] == "high"
    )
    high_or_solved_pct = (high_or_solved / len(all_emitted) * 100.0) if all_emitted else 0.0

    defect_counts: dict[str, int] = {}
    for r in all_emitted:
        dc = r["reference"]["defect_class"]
        defect_counts[dc] = defect_counts.get(dc, 0) + 1

    logger.info(
        "[build_dataset] Emitted total=%d records (eval=%d, val=%d, multi_img=%d) | neg_controls=%d | non_defect_dropped=%d | crossposts_deduped=%d | solved_or_high_conf=%.1f%% | schema_errors=%d",
        len(all_emitted),
        len(eval_records),
        len(val_records),
        multi_image_count,
        len(negative_control_records),
        len(excluded_non_defect),
        len(crosspost_dropped),
        high_or_solved_pct,
        schema_errors,
    )
    return {
        "stage": "build_dataset",
        "total_records": len(all_emitted),
        "eval_records": len(eval_records),
        "val_records": len(val_records),
        "multi_image_records": multi_image_count,
        "negative_control_records": len(negative_control_records),
        "non_defect_dropped": len(excluded_non_defect),
        "crossposts_dropped": len(crosspost_dropped),
        "missing_synthesis": missing_synthesis,
        "missing_raw": missing_raw,
        "schema_errors": schema_errors,
        "solved_or_high_confidence_ratio": round(high_or_solved_pct / 100.0, 4),
        "defect_distribution": defect_counts,
        "eval_path": str(eval_path),
        "val_path": str(val_path),
        "negative_controls_path": str(neg_path),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S6: Build dataset/eval.jsonl and dataset/val.jsonl.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR, help="Path to schema directory")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument(
        "--final-release",
        action="store_true",
        help="Assign 100%% of records to 'test' in eval.jsonl with empty val.jsonl",
    )
    parser.add_argument("--val-ratio", type=float, default=None, help="Override validation split ratio (default 0.10)")
    parser.add_argument(
        "--harvest-showcase-negatives",
        action="store_true",
        help="Visually verify discarded showcase prints in isolation to expand negative_controls.jsonl (<=1/post)",
    )
    parser.add_argument(
        "--fetch-clean-controls",
        type=int,
        default=0,
        help="Target number of independent, isolation-verified clean print controls in negative_controls.jsonl",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_build_dataset(
        config,
        data_dir=args.data_dir,
        schema_dir=args.schema_dir,
        final_release=args.final_release,
        val_ratio_override=args.val_ratio,
        harvest_showcase_negatives=args.harvest_showcase_negatives,
        fetch_clean_controls_target=args.fetch_clean_controls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
