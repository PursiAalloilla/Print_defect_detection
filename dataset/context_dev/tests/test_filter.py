"""Offline unit tests for Stage S3 filtering, lexicon matching, and solved status detection."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

from src.common import DEFAULT_CONFIG_PATH, DEFAULT_LEXICON_PATH, load_config, read_json, read_jsonl, write_json
from src.filter import evaluate_thread, load_lexicon_patterns, run_filter

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _sub_rules() -> dict[str, dict]:
    cfg = load_config(DEFAULT_CONFIG_PATH)
    return {str(s["name"]).lower(): s for s in cfg["subreddits"]}


def test_accepts_fixmyprint_solved_thread() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json")

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is True
    assert decision["reasons"] == []
    assert decision["record_id"] == "fixmyprint_1abcde"
    assert decision["non_deleted_comment_count"] == 6
    assert decision["solved"] is True
    assert str(decision["solved_source"]).startswith("flair:")
    assert len(decision["accepted_images"]) == 1


def test_fixmyprint_passes_even_without_lexicon_keywords() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = copy.deepcopy(read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    thread["post"]["title"] = "Weird diagonal ridges on side wall"
    thread["post"]["body"] = "PLA at 205C on Prusa MK4."
    thread["post"]["flair"] = None
    thread["comments"][0]["replies"][0]["body"] = "Interesting idea, I will test tomorrow."

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is True
    assert decision["lexicon_match"] is None
    assert decision["solved"] is False


def test_rejects_3dprinting_showcase_missing_lexicon() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = read_json(FIXTURES_DIR / "3dprinting_showcase_rejected.json")

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is False
    assert "lexicon_mismatch" in decision["reasons"]


def test_accepts_3dprinting_thread_when_lexicon_matches() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = copy.deepcopy(read_json(FIXTURES_DIR / "3dprinting_showcase_rejected.json"))
    thread["post"]["title"] = "Terrible layer shift halfway up my print, help!"

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is True
    assert decision["lexicon_match"] is not None


def test_rejects_small_thumbnail_and_deleted_comments_and_unsolved_negation() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = read_json(FIXTURES_DIR / "fixmyprint_small_thumb_and_few_comments.json")

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is False
    assert "no_qualifying_image" in decision["reasons"]
    assert any(r.startswith("insufficient_non_deleted_comments:3") for r in decision["reasons"])
    assert decision["solved"] is False


def test_detects_submitter_confirmation_when_flair_absent() -> None:
    patterns = load_lexicon_patterns(DEFAULT_LEXICON_PATH)
    thread = copy.deepcopy(read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    thread["post"]["flair"] = "Question"

    decision = evaluate_thread(thread, lexicon_patterns=patterns, subreddit_rules=_sub_rules())
    assert decision["accepted"] is True
    assert decision["solved"] is True
    assert decision["solved_source"] == "submitter_comment:c2"


def test_run_filter_writes_accepted_and_discarded_and_optional_image_classify(tmp_path: Path) -> None:
    cfg = load_config(DEFAULT_CONFIG_PATH)
    raw_dir = tmp_path / "raw_threads"
    write_json(raw_dir / "FixMyPrint_1abcde.json", read_json(FIXTURES_DIR / "fixmyprint_solved_stringing.json"))
    write_json(raw_dir / "3Dprinting_2showc.json", read_json(FIXTURES_DIR / "3dprinting_showcase_rejected.json"))

    summary = run_filter(cfg, data_dir=tmp_path)
    assert summary["accepted"] == 1
    assert summary["discarded"] == 1

    accepted = read_jsonl(tmp_path / "filtered_threads.jsonl")
    discarded = read_jsonl(tmp_path / "discarded.jsonl")
    assert len(accepted) == 1 and accepted[0]["record_id"] == "fixmyprint_1abcde"
    assert len(discarded) == 1 and "lexicon_mismatch" in discarded[0]["reasons"]

    fake_page = SimpleNamespace(
        request_id="req_img_1",
        key_metadata=SimpleNamespace(credits_consumed=1, credits_remaining=999),
        images=SimpleNamespace(
            success=True,
            error_code=None,
            data=[
                SimpleNamespace(
                    url="https://www.redditstatic.com/icon.png",
                    file_url=None,
                    width=512,
                    height=512,
                    classification="logo",
                    alt="Logo",
                )
            ],
        ),
    )
    fake_client = SimpleNamespace(
        web=SimpleNamespace(scrape=lambda **kwargs: fake_page),
        close=lambda: None,
    )
    summary_cls = run_filter(cfg, data_dir=tmp_path, classify_images=True, client=fake_client)  # type: ignore[arg-type]
    assert summary_cls["accepted"] == 0
    discarded_cls = read_jsonl(tmp_path / "discarded.jsonl")
    assert any("no_photography_image" in row["reasons"] for row in discarded_cls)
