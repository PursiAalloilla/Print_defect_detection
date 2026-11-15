"""Offline JSON Schema validation tests for synthesis output (S5) and dataset records (S6)."""

from __future__ import annotations

import copy

from jsonschema import Draft202012Validator

from src.common import DEFAULT_SCHEMA_DIR, read_json
from src.synthesize import validate_synthesis_output


def _synthesis_validator() -> Draft202012Validator:
    return Draft202012Validator(read_json(DEFAULT_SCHEMA_DIR / "synthesis.schema.json"))


def _record_validator() -> Draft202012Validator:
    return Draft202012Validator(read_json(DEFAULT_SCHEMA_DIR / "record.schema.json"))


VALID_SYNTHESIS = {
    "defect_class": "stringing",
    "defect_class_free": None,
    "printer_context": "Ender 3 V2, Overture PETG at 245C nozzle / 80C bed, Cura",
    "likely_causes": [
        "Moisture absorbed by hygroscopic PETG filament",
        "Excessive nozzle printing temperature (245C)",
    ],
    "recommended_fixes": [
        "Dry PETG spool at 65C for 6 hours",
        "Lower nozzle temperature to 230-235C",
    ],
    "community_consensus": "Commenters overwhelmingly agreed the PETG was wet and printed too hot at 245C. The submitter confirmed drying the spool and dropping to 232C eliminated the stringing.",
    "confidence": "high",
    "solved": True,
    "evidence_comment_ids": ["c1", "c2", "c5"],
}


VALID_RECORD = {
    "id": "fixmyprint_1abcde",
    "source": {
        "platform": "reddit",
        "subreddit": "FixMyPrint",
        "url": "https://www.reddit.com/r/FixMyPrint/comments/1abcde/heavy_cobwebs_between_towers/",
        "retrieved_at": "2026-11-14T20:00:00Z",
    },
    "context": {
        "title": "Heavy cobwebs between towers on my Ender 3 V2 PETG print",
        "body_excerpt": "Printing Overture PETG at 245C nozzle, 80C bed, 4mm retraction at 25mm/s in Cura.",
        "printer_context": "Ender 3 V2, Overture PETG at 245C nozzle / 80C bed, Cura",
    },
    "images": [
        {
            "path": "images/fixmyprint_1abcde_0.jpg",
            "sha256": "a" * 64,
            "width": 1200,
            "height": 900,
        }
    ],
    "reference": {
        "defect_class": "stringing",
        "likely_causes": ["Moisture in PETG", "Nozzle temp too high"],
        "recommended_fixes": ["Dry spool at 65C", "Lower temp to 232C"],
        "community_consensus": "Commenters agreed wet PETG and 245C nozzle caused stringing, confirmed fixed by OP.",
        "confidence": "high",
        "solved": True,
    },
    "quality": {
        "min_comment_score": 6,
        "comment_count": 7,
        "upvote_ratio": 0.96,
    },
    "splits": "test",
}


def test_valid_synthesis_passes_schema() -> None:
    validator = _synthesis_validator()
    errs = validate_synthesis_output(VALID_SYNTHESIS, validator, valid_comment_ids={"c1", "c2", "c5"})
    assert errs == []


def test_synthesis_other_requires_free_text_label() -> None:
    validator = _synthesis_validator()
    bad = copy.deepcopy(VALID_SYNTHESIS)
    bad["defect_class"] = "other"
    bad["defect_class_free"] = None

    errs = validate_synthesis_output(bad, validator)
    assert len(errs) >= 1

    good = copy.deepcopy(bad)
    good["defect_class_free"] = "heat creep jam"
    assert validate_synthesis_output(good, validator) == []


def test_synthesis_rejects_unknown_taxonomy_too_many_causes_and_fake_comment_ids() -> None:
    validator = _synthesis_validator()

    bad_tax = copy.deepcopy(VALID_SYNTHESIS)
    bad_tax["defect_class"] = "melted_plastic"
    assert validate_synthesis_output(bad_tax, validator) != []

    too_many = copy.deepcopy(VALID_SYNTHESIS)
    too_many["likely_causes"] = ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert validate_synthesis_output(too_many, validator) != []

    extra_prop = copy.deepcopy(VALID_SYNTHESIS)
    extra_prop["unexpected_field"] = 123
    assert validate_synthesis_output(extra_prop, validator) != []

    fake_ids = validate_synthesis_output(VALID_SYNTHESIS, validator, valid_comment_ids={"c1"})
    assert any("evidence_comment_ids" in e for e in fake_ids)


def test_valid_dataset_record_passes_and_invalid_rejected() -> None:
    validator = _record_validator()
    assert list(validator.iter_errors(VALID_RECORD)) == []

    no_img = copy.deepcopy(VALID_RECORD)
    no_img["images"] = []
    assert list(validator.iter_errors(no_img)) != []

    bad_sha = copy.deepcopy(VALID_RECORD)
    bad_sha["images"][0]["sha256"] = "not-a-sha256"
    assert list(validator.iter_errors(bad_sha)) != []

    bad_split = copy.deepcopy(VALID_RECORD)
    bad_split["splits"] = "train"
    assert list(validator.iter_errors(bad_split)) != []
