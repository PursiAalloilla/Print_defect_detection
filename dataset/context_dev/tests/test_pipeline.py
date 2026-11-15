"""Offline unit and integration tests for S1, S2, S4, S5, S6, S7, and common utilities."""

from __future__ import annotations

import base64
import copy
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.build_dataset import run_build_dataset
from src.common import (
    BudgetExceededError,
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCHEMA_DIR,
    MissingCredentialsError,
    RunTracker,
    canonical_defect_class,
    coarse_defect_group,
    init_context_client,
    load_config,
    parse_image_dimensions,
    read_json,
    read_jsonl,
    redact_secrets,
    write_json,
    write_jsonl,
)
from src.discover import run_discovery
from src.download import run_download
from src.evaluate import aggregate_variant_metrics, build_task_messages, run_evaluate
from src.fetch import parse_shreddit_comments_tree, run_fetch
from src.filter import run_filter
from src.synthesize import prepare_thread_for_synthesis, run_synthesize

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _make_png_bytes(width: int = 800, height: int = 600, color: tuple[int, int, int] = (200, 60, 40)) -> bytes:
    """Create a valid minimal RGB PNG image in memory using pure stdlib."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(color) * width
    idat = zlib.compress(row * height, level=1)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def test_png_dimensions_and_secret_redaction_and_budget_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = _make_png_bytes(640, 480)
    assert parse_image_dimensions(png) == (640, 480)

    leaked = "Error with key ctxt_secret_AbCdEf123456 and header Bearer secret_tok_99"
    redacted = redact_secrets(leaked)
    assert "ctxt_secret_" not in redacted
    assert "secret_tok_99" not in redacted

    monkeypatch.delenv("CONTEXT_DEV_API_KEY", raising=False)
    # Point load_environment away from any real .env
    monkeypatch.setattr("src.common.load_environment", lambda *a, **kw: None)
    with pytest.raises(MissingCredentialsError):
        init_context_client({})

    tracker = RunTracker(stage="test", max_requests=1, data_dir=tmp_path)
    tracker.record_response(
        {"request_id": "req_1", "key_metadata": {"credits_consumed": 1, "credits_remaining": 99}},
        operation="scrape",
    )
    with pytest.raises(BudgetExceededError):
        tracker.check_budget(1)


def test_shreddit_html_comment_tree_fallback_and_automod_filter() -> None:
    sample_html = """
    <shreddit-comment thingid="t1_bot1" depth="0" score="1" author="AutoModerator" permalink="/r/FixMyPrint/comments/1a/comment/bot1/">
      <div id="t1_bot1-comment-rtjson-content" slot="comment"><p>Automated reminder.</p></div>
    </shreddit-comment>
    <shreddit-comment thingid="t1_top1" depth="0" score="32" author="helper_a" permalink="/r/FixMyPrint/comments/1a/comment/top1/">
      <div id="t1_top1-comment-rtjson-content" slot="comment"><p>Dry your filament and lower temp.</p></div>
    </shreddit-comment>
    <shreddit-comment thingid="t1_rep1" depth="1" parentid="t1_top1" score="9" is-op="" author="op_user" permalink="/r/FixMyPrint/comments/1a/comment/rep1/">
      <div id="t1_rep1-comment-rtjson-content" slot="comment"><p>That worked, thank you!</p></div>
    </shreddit-comment>
    """
    tree = parse_shreddit_comments_tree(sample_html)
    assert len(tree) == 2
    assert tree[1]["id"] == "top1"
    assert tree[1]["score"] == 32
    assert len(tree[1]["replies"]) == 1
    assert tree[1]["replies"][0]["id"] == "rep1"
    assert tree[1]["replies"][0]["is_submitter"] is True


def test_s1_discovery_deduplicates_and_filters(tmp_path: Path) -> None:
    cfg = load_config(DEFAULT_CONFIG_PATH)

    raw_posts = [
        {
            "id": "1abcde",
            "subreddit": "FixMyPrint",
            "type": "image",
            "title": "Stringing help",
            "flair": "Solved!",
            "score": 84,
            "upvote_ratio": 0.96,
            "comment_count": 7,
            "is_nsfw": False,
            "removed_by": None,
            "images": [{"url": "https://i.redd.it/example1abcde.jpg", "width": 1200, "height": 900}],
        },
        {
            "id": "textonly",
            "subreddit": "FixMyPrint",
            "type": "text",
            "title": "Text question",
            "score": 50,
            "comment_count": 20,
            "is_nsfw": False,
            "removed_by": None,
        },
        {
            "id": "nsfwpost",
            "subreddit": "FixMyPrint",
            "type": "image",
            "title": "NSFW print",
            "score": 50,
            "comment_count": 20,
            "is_nsfw": True,
            "removed_by": None,
        },
    ]

    fake_page = SimpleNamespace(
        request_id="req_disc_1",
        key_metadata=SimpleNamespace(credits_consumed=1, credits_remaining=998),
        parsed=SimpleNamespace(
            success=True,
            error_code=None,
            message=None,
            data={"posts": raw_posts, "has_more": False},
        ),
    )
    fake_client = SimpleNamespace(
        web=SimpleNamespace(scrape=lambda **kwargs: fake_page),
        close=lambda: None,
    )

    summary = run_discovery(
        cfg,
        data_dir=tmp_path,
        client=fake_client,  # type: ignore[arg-type]
        subreddits_override=["FixMyPrint"],
        max_queries=2,
    )
    # Same post returned across 2 queries must deduplicate to 1 candidate
    assert summary["total_candidates"] == 1
    cands = read_jsonl(tmp_path / "candidates.jsonl")
    assert len(cands) == 1
    assert cands[0]["id"] == "1abcde"
    assert len(cands[0]["discovered_via"]) == 2


def test_s2_fetch_batch_mode(tmp_path: Path) -> None:
    cfg = load_config(DEFAULT_CONFIG_PATH)
    write_jsonl(
        tmp_path / "candidates.jsonl",
        [{"id": "1abcde", "subreddit": "FixMyPrint", "comment_count": 7, "score": 84}],
    )
    thread_fixture = read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json")

    fake_submit_resp = SimpleNamespace(
        id="batch_test_1",
        status="queued",
        request_id="req_bsub",
        key_metadata=SimpleNamespace(credits_consumed=0, credits_remaining=998),
        input=SimpleNamespace(submitted=1, reserved=1),
        credits=SimpleNamespace(reserved=1),
        invalid_urls=[],
    )
    fake_retrieve_resp = SimpleNamespace(
        id="batch_test_1",
        status="completed",
        request_id="req_bret",
        key_metadata=SimpleNamespace(credits_consumed=0, credits_remaining=997),
        progress=SimpleNamespace(succeeded=1, failed=0, pending=0),
        credits=SimpleNamespace(reserved=1, refunded=0, net=1),
        failure=None,
    )
    fake_results_resp = SimpleNamespace(
        request_id="req_bres",
        key_metadata=SimpleNamespace(credits_consumed=0, credits_remaining=997),
        has_more=False,
        next_cursor=None,
        data=[
            SimpleNamespace(
                status="ok",
                item_id="FixMyPrint_1abcde",
                meta={"subreddit": "FixMyPrint", "post_id": "1abcde"},
                url="https://www.reddit.com/r/FixMyPrint/comments/1abcde?sort=top",
                credits_used=1,
                result=SimpleNamespace(
                    request_id="req_item_1",
                    parsed=SimpleNamespace(
                        success=True,
                        error_code=None,
                        message=None,
                        data=thread_fixture,
                    ),
                ),
            )
        ],
    )

    batch_ns = SimpleNamespace(
        submit=lambda **kwargs: fake_submit_resp,
        retrieve=lambda batch_id: fake_retrieve_resp,
        get_results=lambda batch_id, **kwargs: fake_results_resp,
    )
    fake_client = SimpleNamespace(
        batch=batch_ns,
        with_options=lambda **kwargs: SimpleNamespace(batch=batch_ns),
        close=lambda: None,
    )

    summary = run_fetch(cfg, data_dir=tmp_path, client=fake_client, force_batch=True)  # type: ignore[arg-type]
    assert summary["mode"] == "batch"
    assert summary["succeeded"] == 1
    assert (tmp_path / "raw_threads" / "FixMyPrint_1abcde.json").is_file()


def test_end_to_end_offline_s3_to_s7_with_crosspost_dedupe_and_retry(tmp_path: Path) -> None:
    cfg = load_config(DEFAULT_CONFIG_PATH)

    # Create two raw threads sharing the exact same image bytes (crosspost simulation)
    # plus a third low-confidence thread to verify separate low-confidence reporting in S7.
    t1 = copy.deepcopy(read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    t2_cross = copy.deepcopy(t1)
    t2_cross["post"]["id"] = "9xpost"
    t2_cross["post"]["subreddit"] = "3Dprinting"
    t2_cross["post"]["comment_count"] = 6
    t2_cross["post"]["score"] = 15

    # Give t1 higher comment_count so t1 wins crosspost deduplication
    t1["post"]["comment_count"] = 45

    t3_low = copy.deepcopy(t1)
    t3_low["post"]["id"] = "7uncrt"
    t3_low["post"]["flair"] = None
    t3_low["post"]["images"][0]["url"] = "https://i.redd.it/other7uncrt.png"
    t3_low["comments"][0]["replies"][0]["body"] = "Thanks, I will check both ideas."

    raw_dir = tmp_path / "raw_threads"
    write_json(raw_dir / "FixMyPrint_1abcde.json", t1)
    write_json(raw_dir / "3Dprinting_9xpost.json", t2_cross)
    write_json(raw_dir / "FixMyPrint_7uncrt.json", t3_low)

    # Verify pseudonymization strips real Reddit usernames
    prepared, valid_ids = prepare_thread_for_synthesis(t1)
    serialized_prepared = json.dumps(prepared)
    assert "maker_op" not in serialized_prepared
    assert "helper_one" not in serialized_prepared
    assert "author_1" in serialized_prepared
    assert "c2" in valid_ids

    # S3 filter
    f_sum = run_filter(cfg, data_dir=tmp_path)
    assert f_sum["accepted"] == 3

    # S4 download with mocked bytes (same PNG for t1 & t2_cross; distinct PNG for t3_low; plus HTML rejection check)
    png_shared = _make_png_bytes(800, 600, (220, 50, 50))
    png_distinct = _make_png_bytes(800, 600, (40, 120, 220))

    def _fake_bytes_scrape(**kwargs: Any) -> Any:
        url = kwargs["url"]
        payload = png_distinct if "other7uncrt" in url else png_shared
        return SimpleNamespace(
            request_id="req_dl",
            key_metadata=SimpleNamespace(credits_consumed=1, credits_remaining=990),
            bytes=SimpleNamespace(
                success=True,
                error_code=None,
                message=None,
                data=SimpleNamespace(
                    content_type="image/png",
                    base64=base64.b64encode(payload).decode("ascii"),
                ),
            ),
        )

    dl_client = SimpleNamespace(web=SimpleNamespace(scrape=_fake_bytes_scrape), close=lambda: None)
    dl_sum = run_download(cfg, data_dir=tmp_path, client=dl_client)  # type: ignore[arg-type]
    assert dl_sum["downloaded"] == 3

    # S5 synthesize: simulate 1 invalid schema response followed by valid retry on first thread
    call_counter = {"n": 0}

    def _fake_synth_create(**kwargs: Any) -> Any:
        call_counter["n"] += 1
        user_msg = json.dumps(kwargs["messages"][1]["content"])
        if call_counter["n"] == 1:
            # Deliberately invalid defect_class to trigger 1-retry path
            bad_json = json.dumps({"defect_class": "not_in_enum"})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=bad_json))])

        is_low_thread = "other7uncrt" in user_msg or "will check both ideas" in user_msg
        good = {
            "defect_class": "warping" if is_low_thread else "stringing",
            "defect_class_free": None,
            "printer_context": "Ender 3 V2, PETG",
            "likely_causes": ["Wet PETG filament", "Nozzle temp too high"],
            "recommended_fixes": ["Dry filament at 65C", "Drop nozzle to 232C"],
            "community_consensus": "Commenters agreed wet filament and excessive temp caused stringing; disagreed on Z-hop." if is_low_thread else "Strong consensus on wet PETG and high temperature, confirmed fixed by OP.",
            "confidence": "low" if is_low_thread else "high",
            "solved": False if is_low_thread else True,
            "evidence_comment_ids": ["c1", "c4"],
            "shows_failed_print": True,
            "image_roles": [{"image_index": 0, "role": "failed_print"}],
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(good)))])

    fake_llm = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_fake_synth_create))
    )
    s_sum = run_synthesize(cfg, data_dir=tmp_path, schema_dir=DEFAULT_SCHEMA_DIR, llm_client=fake_llm)  # type: ignore[arg-type]
    assert s_sum["passed"] == 3
    assert s_sum["retry_passed"] == 1
    assert s_sum["validation_pass_rate"] == 1.0

    # S6 build_dataset (final_release=True puts all non-duplicate records into eval.jsonl)
    b_sum = run_build_dataset(cfg, data_dir=tmp_path, schema_dir=DEFAULT_SCHEMA_DIR, final_release=True)
    # Crosspost 3dprinting_9xpost dropped because fixmyprint_1abcde has higher comment_count (45 > 6)
    assert b_sum["crossposts_dropped"] == 1
    assert b_sum["eval_records"] == 2
    eval_rows = read_jsonl(tmp_path / "dataset" / "eval.jsonl")
    emitted_ids = {r["id"] for r in eval_rows}
    assert emitted_ids == {"fixmyprint_1abcde", "fixmyprint_7uncrt"}

    # Verify Variant A (pure visual), Variant T (telemetry-only), and Variant B (full user context)
    sample_rec = next(r for r in eval_rows if r["id"] == "fixmyprint_1abcde")
    msgs_a = build_task_messages(sample_rec, variant="A", data_dir=tmp_path)
    msgs_t = build_task_messages(sample_rec, variant="T", data_dir=tmp_path)
    msgs_b = build_task_messages(sample_rec, variant="B", data_dir=tmp_path)
    text_a = msgs_a[1]["content"][0]["text"]
    text_t = msgs_t[1]["content"][0]["text"]
    text_b = msgs_b[1]["content"][0]["text"]
    assert "Heavy cobwebs" not in text_a
    assert "Ender 3 V2" not in text_a
    assert "Overture PETG at 245C" not in text_a
    assert "Ender 3 V2" in text_t
    assert "Heavy cobwebs" not in text_t
    assert "Overture PETG at 245C" not in text_t
    assert "Heavy cobwebs" in text_b
    assert "Ender 3 V2" in text_b
    assert "Overture PETG at 245C" in text_b

    # S7 evaluate with mocked model-under-test and blind A/B judge
    def _fake_mut_create(**kwargs: Any) -> Any:
        pred = {
            "defect_class": "stringing",
            "likely_causes": ["Wet PETG", "High nozzle temperature"],
            "recommended_fixes": ["Dry spool", "Lower temperature to 232C"],
            "community_consensus": "Stringing from moisture and heat.",
            "confidence": "high",
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(pred)))])

    def _fake_judge_create(**kwargs: Any) -> Any:
        j = {
            "answer_a": {"causes_score": 2, "fixes_score": 2},
            "answer_b": {"causes_score": 2, "fixes_score": 2},
            "justification": "Both answers identify wet PETG and excessive nozzle temperature with actionable drying and temperature fixes.",
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(j)))])

    mut_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_fake_mut_create)))
    jdg_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_fake_judge_create)))

    eval_report = run_evaluate(
        cfg,
        data_dir=tmp_path,
        model_client=mut_client,  # type: ignore[arg-type]
        judge_client=jdg_client,  # type: ignore[arg-type]
        compare_model_client=mut_client,  # type: ignore[arg-type]
        compare_model_override="candidate-model-y",
    )
    assert eval_report["records_evaluated"] == 2
    assert set(eval_report["variants"].keys()) == {"A", "T", "B"}
    assert eval_report["pairwise_ab"] is not None
    assert eval_report["pairwise_ab"]["model_y"] == "candidate-model-y"
    assert (tmp_path / "eval_runs" / "pairwise_ab.jsonl").is_file()
    var_a = eval_report["variants"]["A"]
    assert var_a["primary_high_medium_confidence"]["count"] == 1
    assert var_a["primary_high_medium_confidence"]["exact_match_accuracy"] == 1.0
    assert var_a["low_confidence_reference_separate"]["count"] == 1
    assert (tmp_path / "eval_runs" / "eval_report.md").is_file()


def test_visual_gate_negative_controls_synonym_collapse_and_error_exclusion(tmp_path: Path) -> None:
    assert canonical_defect_class("ghosting") == canonical_defect_class("ringing")
    assert canonical_defect_class("oozing") == canonical_defect_class("stringing")
    assert coarse_defect_group("first_layer") == coarse_defect_group("bed_adhesion")

    # Verify errored items are excluded from accuracy and mean score denominators
    agg = aggregate_variant_metrics(
        [
            {
                "id": "ok1",
                "variant": "A",
                "reference_defect_class": "ringing",
                "predicted_defect_class": "ghosting",
                "exact_match": False,
                "synonym_match": True,
                "coarse_match": True,
                "reference_confidence": "high",
                "reference_solved": True,
                "judge": {"causes_score": 2, "fixes_score": 2, "judge_error": None},
                "model_error": None,
            },
            {
                "id": "err1",
                "variant": "A",
                "reference_defect_class": "stringing",
                "predicted_defect_class": None,
                "exact_match": None,
                "synonym_match": None,
                "coarse_match": None,
                "reference_confidence": "high",
                "reference_solved": True,
                "judge": {"causes_score": None, "fixes_score": None, "judge_error": "timeout"},
                "model_error": "API timeout",
            },
        ]
    )
    prim = agg["primary_high_medium_confidence"]
    assert prim["count"] == 1
    assert prim["excluded_errors"] == 1
    assert prim["exact_match_accuracy"] == 0.0
    assert prim["synonym_collapsed_accuracy"] == 1.0
    assert prim["causes_score_mean"] == 2.0

    # Verify build_dataset drops hardware-only records and emits clean_print images to negative_controls.jsonl
    cfg = load_config(DEFAULT_CONFIG_PATH)
    t_hw = copy.deepcopy(read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    t_hw["post"]["id"] = "hwonly"
    t_gal = copy.deepcopy(read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    t_gal["post"]["id"] = "mixgal"
    t_gal["post"]["images"] = [
        {"url": "https://i.redd.it/clean0.png", "width": 800, "height": 600, "caption": "Fixed 1"},
        {"url": "https://i.redd.it/clean1.png", "width": 800, "height": 600, "caption": "Fixed 2"},
        {"url": "https://i.redd.it/fail2.png", "width": 800, "height": 600, "caption": "Before"},
    ]
    write_json(tmp_path / "raw_threads" / "FixMyPrint_hwonly.json", t_hw)
    write_json(tmp_path / "raw_threads" / "FixMyPrint_mixgal.json", t_gal)
    run_filter(cfg, data_dir=tmp_path)

    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for rid, im_idx, col in [
        ("fixmyprint_hwonly", 0, (10, 20, 30)),
        ("fixmyprint_mixgal", 0, (40, 50, 60)),
        ("fixmyprint_mixgal", 1, (55, 65, 75)),
        ("fixmyprint_mixgal", 2, (70, 80, 90)),
    ]:
        p = img_dir / f"{rid}_{im_idx}.png"
        p.write_bytes(_make_png_bytes(800, 600, col))
    write_jsonl(
        tmp_path / "assets.jsonl",
        [
            {"record_id": "fixmyprint_hwonly", "image_index": 0, "path": "images/fixmyprint_hwonly_0.png", "sha256": "1" * 64, "width": 800, "height": 600},
            {"record_id": "fixmyprint_mixgal", "image_index": 0, "path": "images/fixmyprint_mixgal_0.png", "sha256": "2" * 64, "width": 800, "height": 600},
            {"record_id": "fixmyprint_mixgal", "image_index": 1, "path": "images/fixmyprint_mixgal_1.png", "sha256": "3" * 64, "width": 800, "height": 600},
            {"record_id": "fixmyprint_mixgal", "image_index": 2, "path": "images/fixmyprint_mixgal_2.png", "sha256": "4" * 64, "width": 800, "height": 600},
        ],
    )
    write_json(
        tmp_path / "records" / "fixmyprint_hwonly.json",
        {
            "synthesis": {
                "defect_class": "other",
                "defect_class_free": "extruder wear",
                "printer_context": None,
                "likely_causes": ["Abrasive filament"],
                "recommended_fixes": ["Metal extruder"],
                "community_consensus": "Hardware wear on extruder inlet.",
                "confidence": "high",
                "solved": True,
                "evidence_comment_ids": ["c1"],
                "shows_failed_print": False,
                "image_roles": [{"image_index": 0, "role": "hardware_closeup"}],
            }
        },
    )
    write_json(
        tmp_path / "records" / "fixmyprint_mixgal.json",
        {
            "synthesis": {
                "defect_class": "stringing",
                "defect_class_free": None,
                "printer_context": "Ender 3 V2",
                "likely_causes": ["Wet PETG"],
                "recommended_fixes": ["Dry spool"],
                "community_consensus": "Wet PETG caused stringing; image 0 shows after drying.",
                "confidence": "high",
                "solved": True,
                "evidence_comment_ids": ["c1"],
                "shows_failed_print": True,
                "image_roles": [
                    {"image_index": 0, "role": "clean_print"},
                    {"image_index": 1, "role": "clean_print"},
                    {"image_index": 2, "role": "failed_print"},
                ],
            }
        },
    )
    b_res = run_build_dataset(cfg, data_dir=tmp_path, schema_dir=DEFAULT_SCHEMA_DIR, final_release=True)
    assert b_res["non_defect_dropped"] == 1
    assert b_res["eval_records"] == 1
    # 2 clean_print images in mixgal must deduplicate to <= 1 negative control per post
    assert b_res["negative_control_records"] == 1
    pos = read_jsonl(tmp_path / "dataset" / "eval.jsonl")
    neg = read_jsonl(tmp_path / "dataset" / "negative_controls.jsonl")
    assert pos[0]["id"] == "fixmyprint_mixgal"
    assert [im["path"] for im in pos[0]["images"]] == ["images/fixmyprint_mixgal_2.png"]
    assert neg[0]["reference"]["defect_class"] == "clean"
