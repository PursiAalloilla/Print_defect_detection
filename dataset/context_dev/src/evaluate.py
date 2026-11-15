"""Stage S7: Leak-free multimodal evaluation harness, rubric judge, blind Model-vs-Model A/B comparison, and negative controls."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from src.common import (
    DEFECT_TAXONOMY,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    canonical_defect_class,
    coarse_defect_group,
    encode_image_as_data_url,
    init_llm_client,
    load_config,
    load_environment,
    read_jsonl,
    setup_logging,
    utc_now_iso,
    write_json,
    write_jsonl,
)
from src.synthesize import extract_message_text, parse_json_response

PREDICTION_CLASSES: tuple[str, ...] = (*DEFECT_TAXONOMY, "clean")

MODEL_SYSTEM_PROMPT = f"""You are a 3D-printing visual quality & failure diagnosis assistant.
Examine the provided photograph(s) (and any provided post metadata in Variant B).
- If the 3D print in the photograph is clean/successful with no visible print defect, set "defect_class" to "clean" and return empty arrays [] for "likely_causes" and "recommended_fixes".
- Otherwise, classify the primary print defect into ONE of:
{", ".join(DEFECT_TAXONOMY)}
and list the most likely causes (ordered most likely first, max 5) and most actionable fixes (ordered most actionable first, max 5).

Respond with ONLY a valid JSON object matching this exact structure:
{{
  "defect_class": "one of the taxonomy values above (or clean)",
  "likely_causes": ["most likely cause 1", "cause 2"],
  "recommended_fixes": ["most actionable fix 1", "fix 2"],
  "community_consensus": "2-4 sentence diagnostic summary",
  "confidence": "high | medium | low"
}}"""


RUBRIC_JUDGE_SYSTEM_PROMPT = """You are an expert, impartial 3D-printing troubleshooting evaluator.
You are given:
1. The photograph(s) of the 3D print,
2. The Ground-Truth Reference Rubric synthesized from the troubleshooting thread (established defect_class, reference likely_causes, reference recommended_fixes, community_consensus, and whether the OP confirmed a fix),
3. A Candidate Model's Diagnosis (predicted defect_class, likely_causes, recommended_fixes).

Grade the Candidate Model's causes and fixes on 0–2 scales WITHOUT penalizing phrasing or stylistic differences from the reference summary:
- "causes_score" (integer 0, 1, or 2):
  * 2 = Accurately identifies the primary root cause(s) established in the reference rubric.
  * 1 = Partially correct, or identifies visually plausible mechanical/slicer causes visible in the photo when the exact confirmed cause required non-visual thread context.
  * 0 = Visually contradicted by the photograph, mechanically wrong, or irrelevant.
- "fixes_score" (integer 0, 1, or 2):
  * 2 = Specific, actionable troubleshooting steps aligned with the effective fix(es) in the reference rubric.
  * 1 = Partially aligned or reasonable general troubleshooting steps for the visible symptom, but misses the key fix.
  * 0 = Wrong, counterproductive, or irrelevant advice.

Also return "justification": one concise sentence explaining the grades.

Respond with ONLY a valid JSON object:
{
  "causes_score": 0,
  "fixes_score": 0,
  "justification": "One concise sentence explaining the scores."
}"""


PAIRWISE_AB_JUDGE_SYSTEM_PROMPT = """You are an impartial 3D-printing benchmark judge conducting a blind head-to-head comparison between two anonymous candidate models ("Answer A" and "Answer B", randomized).
You are given the print photograph(s) and the Ground-Truth Reference Rubric (defect_class, likely_causes, recommended_fixes, community_consensus).
Score BOTH Answer A and Answer B on "causes_score" (0, 1, or 2) and "fixes_score" (0, 1, or 2), pick "winner" ("A", "B", or "tie"), and give a one-sentence "justification".

Respond with ONLY valid JSON:
{
  "answer_a": {"causes_score": 0, "fixes_score": 0},
  "answer_b": {"causes_score": 0, "fixes_score": 0},
  "winner": "A | B | tie",
  "justification": "One concise sentence."
}"""


def build_task_messages(
    record: dict[str, Any],
    *,
    variant: str,
    data_dir: Path,
) -> list[dict[str, Any]]:
    """Construct messages for Variant A (pure visual), Variant T (telemetry-only), or Variant B (full post context)."""
    if variant not in {"A", "T", "B"}:
        raise ValueError(f"Unsupported evaluation variant: {variant!r} (expected 'A', 'T', or 'B')")

    content_blocks: list[dict[str, Any]] = []
    if variant == "A":
        # Pure visual diagnosis: deliberately exclude title, printer_context, and body_excerpt to prevent label leakage
        content_blocks.append(
            {
                "type": "text",
                "text": (
                    "Inspect ONLY the attached photograph(s) of the 3D print with no text hints. "
                    "Classify the defect (or 'clean' if defect-free) and return strict JSON."
                ),
            }
        )
    elif variant == "T":
        # Printer-telemetry only (Moonraker/Klipper deployment realism): machine/material/temp/speed specs ONLY, zero human title/body
        ctx = record["context"]
        text_prompt = "\n".join(
            [
                f"Printer & Slicer Telemetry: {ctx.get('printer_context') or 'Not available'}",
                "\nInspect the attached photograph(s) together with the machine/filament telemetry above (no user text) and return strict JSON.",
            ]
        )
        content_blocks.append({"type": "text", "text": text_prompt})
    else:
        ctx = record["context"]
        text_prompt = "\n".join(
            [
                f"Post Title: {ctx.get('title') or ''}",
                f"Printer Setup Context: {ctx.get('printer_context') or 'Not specified'}",
                f"Post Body Excerpt: {ctx.get('body_excerpt') or '(empty)'}",
                "\nInspect the attached photograph(s) together with the user's post details above and return strict JSON.",
            ]
        )
        content_blocks.append({"type": "text", "text": text_prompt})

    for img_entry in record.get("images") or []:
        img_path = data_dir / str(img_entry["path"])
        if img_path.is_file():
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(img_path)},
                }
            )

    return [
        {"role": "system", "content": MODEL_SYSTEM_PROMPT},
        {"role": "user", "content": content_blocks},
    ]


def normalize_model_prediction(raw_obj: dict[str, Any]) -> dict[str, Any]:
    """Normalize candidate model JSON prediction into canonical fields."""
    dc = str(raw_obj.get("defect_class") or "other").strip().lower()
    if dc not in PREDICTION_CLASSES:
        dc = "other"

    causes_raw = raw_obj.get("likely_causes")
    causes = (
        [str(x).strip() for x in causes_raw if str(x).strip()][:5]
        if isinstance(causes_raw, list)
        else []
    )
    fixes_raw = raw_obj.get("recommended_fixes")
    fixes = (
        [str(x).strip() for x in fixes_raw if str(x).strip()][:5]
        if isinstance(fixes_raw, list)
        else []
    )
    conf = str(raw_obj.get("confidence") or "medium").strip().lower()
    if conf not in {"high", "medium", "low"}:
        conf = "medium"

    return {
        "defect_class": dc,
        "likely_causes": causes,
        "recommended_fixes": fixes,
        "community_consensus": str(raw_obj.get("community_consensus") or ""),
        "confidence": conf,
    }


def query_model_under_test(
    client: OpenAI,
    *,
    model: str,
    record: dict[str, Any],
    variant: str,
    data_dir: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run model-under-test on one record and variant; return (None, error_str) if both attempts fail."""
    messages = build_task_messages(record, variant=variant, data_dir=data_dir)
    last_err: str | None = None

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = extract_message_text(resp.choices[0].message.content)
            parsed = parse_json_response(content)
            return normalize_model_prediction(parsed), None
        except Exception as exc:
            last_err = str(exc)
            if "free-models-per-day" in last_err or "insufficient credits" in last_err.lower():
                break
            if "429" in last_err or "rate" in last_err.lower():
                time.sleep(6.0 * (attempt + 1))
                continue
            if attempt == 0:
                messages.append(
                    {
                        "role": "user",
                        "content": f"Please return ONLY a valid JSON object. Previous error: {last_err}",
                    }
                )
            else:
                break

    return None, last_err


def _clamp_score(val: Any) -> int:
    try:
        iv = int(val)
    except (TypeError, ValueError):
        return 0
    return max(0, min(2, iv))


def score_candidate_with_rubric_judge(
    judge_client: OpenAI,
    *,
    judge_model: str,
    record: dict[str, Any],
    candidate_pred: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    """Multimodal reference-rubric judge: inspects the image(s) + full reference causes/fixes + candidate output."""
    ref = record["reference"]
    rubric_payload = {
        "reference_rubric": {
            "established_defect_class": ref.get("defect_class"),
            "defect_class_free": ref.get("defect_class_free"),
            "solved_confirmed_by_op": bool(ref.get("solved")),
            "reference_likely_causes": ref.get("likely_causes") or [],
            "reference_recommended_fixes": ref.get("recommended_fixes") or [],
            "community_consensus": ref.get("community_consensus"),
        },
        "candidate_diagnosis": {
            "predicted_defect_class": candidate_pred.get("defect_class"),
            "likely_causes": candidate_pred.get("likely_causes") or [],
            "recommended_fixes": candidate_pred.get("recommended_fixes") or [],
        },
    }

    user_blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Grade the Candidate Diagnosis against the Reference Rubric and attached print photograph(s):\n\n"
                + json.dumps(rubric_payload, ensure_ascii=False, indent=2)
            ),
        }
    ]
    for img_entry in (record.get("images") or [])[:2]:
        img_path = data_dir / str(img_entry["path"])
        if img_path.is_file():
            user_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(img_path)},
                }
            )

    try:
        resp = judge_client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": RUBRIC_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_blocks},  # type: ignore[arg-type]
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp.choices[0].message.content)
        # Backward compatibility if a mocked judge returns answer_a/answer_b format
        if "causes_score" not in parsed and isinstance(parsed.get("answer_a"), dict):
            sub = parsed["answer_a"]
            return {
                "causes_score": _clamp_score(sub.get("causes_score", 0)),
                "fixes_score": _clamp_score(sub.get("fixes_score", 0)),
                "justification": str(parsed.get("justification") or "").strip(),
                "judge_error": None,
            }
        return {
            "causes_score": _clamp_score(parsed.get("causes_score", 0)),
            "fixes_score": _clamp_score(parsed.get("fixes_score", 0)),
            "justification": str(parsed.get("justification") or "").strip(),
            "judge_error": None,
        }
    except Exception as exc:
        return {
            "causes_score": None,
            "fixes_score": None,
            "justification": "",
            "judge_error": str(exc),
        }


def score_pairwise_blind_ab(
    judge_client: OpenAI,
    *,
    judge_model: str,
    record: dict[str, Any],
    pred_model_x: dict[str, Any],
    pred_model_y: dict[str, Any],
    data_dir: Path,
    rng: random.Random,
) -> dict[str, Any]:
    """True blind randomized A/B comparison between two candidate models (Model X vs Model Y)."""
    x_is_a = rng.choice([True, False])
    ans_a = pred_model_x if x_is_a else pred_model_y
    ans_b = pred_model_y if x_is_a else pred_model_x
    ref = record["reference"]

    payload = {
        "reference_rubric": {
            "established_defect_class": ref.get("defect_class"),
            "reference_likely_causes": ref.get("likely_causes") or [],
            "reference_recommended_fixes": ref.get("recommended_fixes") or [],
            "community_consensus": ref.get("community_consensus"),
        },
        "Answer A": {
            "defect_class": ans_a.get("defect_class"),
            "likely_causes": ans_a.get("likely_causes") or [],
            "recommended_fixes": ans_a.get("recommended_fixes") or [],
        },
        "Answer B": {
            "defect_class": ans_b.get("defect_class"),
            "likely_causes": ans_b.get("likely_causes") or [],
            "recommended_fixes": ans_b.get("recommended_fixes") or [],
        },
    }
    user_blocks: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    for img_entry in (record.get("images") or [])[:2]:
        img_path = data_dir / str(img_entry["path"])
        if img_path.is_file():
            user_blocks.append(
                {"type": "image_url", "image_url": {"url": encode_image_as_data_url(img_path)}}
            )

    resp = judge_client.chat.completions.create(
        model=judge_model,
        messages=[
            {"role": "system", "content": PAIRWISE_AB_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_blocks},  # type: ignore[arg-type]
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    parsed = parse_json_response(resp.choices[0].message.content)
    raw_winner = str(parsed.get("winner") or "tie").strip().upper()
    if raw_winner == "A":
        winner = "model_x" if x_is_a else "model_y"
    elif raw_winner == "B":
        winner = "model_y" if x_is_a else "model_x"
    else:
        winner = "tie"

    a_sc = parsed.get("answer_a") or {}
    b_sc = parsed.get("answer_b") or {}
    x_sc = a_sc if x_is_a else b_sc
    y_sc = b_sc if x_is_a else a_sc
    return {
        "model_x_position": "A" if x_is_a else "B",
        "winner": winner,
        "model_x_causes": _clamp_score(x_sc.get("causes_score", 0)),
        "model_x_fixes": _clamp_score(x_sc.get("fixes_score", 0)),
        "model_y_causes": _clamp_score(y_sc.get("causes_score", 0)),
        "model_y_fixes": _clamp_score(y_sc.get("fixes_score", 0)),
        "justification": str(parsed.get("justification") or "").strip(),
    }


def _aggregate_subset(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics over non-errored items; explicitly exclude API errors from denominators."""
    valid_model = [x for x in items if x.get("model_error") is None and x.get("predicted_defect_class") is not None]
    errored_count = len(items) - len(valid_model)
    n = len(valid_model)
    if n == 0:
        return {
            "count": 0,
            "closed_taxonomy_count": 0,
            "excluded_errors": errored_count,
            "exact_match_accuracy": None,
            "closed_taxonomy_accuracy": None,
            "synonym_collapsed_accuracy": None,
            "coarse_group_accuracy": None,
            "causes_score_mean": None,
            "fixes_score_mean": None,
            "causes_score_distribution": {"0": 0, "1": 0, "2": 0},
            "fixes_score_distribution": {"0": 0, "1": 0, "2": 0},
        }

    exact_hits = sum(1 for x in valid_model if x["exact_match"])
    syn_hits = sum(1 for x in valid_model if x["synonym_match"])
    coarse_hits = sum(1 for x in valid_model if x["coarse_match"])

    closed_items = [x for x in valid_model if x["reference_defect_class"] != "other"]
    closed_n = len(closed_items)
    closed_hits = sum(1 for x in closed_items if x["synonym_match"])

    valid_judged = [
        x
        for x in valid_model
        if x["judge"].get("judge_error") is None and x["judge"].get("causes_score") is not None
    ]
    m = len(valid_judged)
    causes_vals = [int(x["judge"]["causes_score"]) for x in valid_judged]
    fixes_vals = [int(x["judge"]["fixes_score"]) for x in valid_judged]

    causes_dist = {str(k): sum(k == v for v in causes_vals) for k in (0, 1, 2)}
    fixes_dist = {str(k): sum(k == v for v in fixes_vals) for k in (0, 1, 2)}

    return {
        "count": n,
        "closed_taxonomy_count": closed_n,
        "excluded_errors": errored_count + (n - m),
        "exact_match_accuracy": round(exact_hits / n, 4),
        "closed_taxonomy_accuracy": round(closed_hits / closed_n, 4) if closed_n > 0 else None,
        "synonym_collapsed_accuracy": round(syn_hits / n, 4),
        "coarse_group_accuracy": round(coarse_hits / n, 4),
        "causes_score_mean": round(sum(causes_vals) / m, 4) if m > 0 else None,
        "fixes_score_mean": round(sum(fixes_vals) / m, 4) if m > 0 else None,
        "causes_score_distribution": causes_dist,
        "fixes_score_distribution": fixes_dist,
    }


def build_confusion_matrix(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Build confusion matrix {ref_class: {pred_class: count}} across valid model predictions."""
    valid = [x for x in items if x.get("model_error") is None and x.get("predicted_defect_class") is not None]
    active_classes = sorted(
        {str(x["reference_defect_class"]) for x in valid} | {str(x["predicted_defect_class"]) for x in valid}
    )
    matrix: dict[str, dict[str, int]] = {
        rc: {pc: 0 for pc in active_classes} for rc in active_classes
    }
    for x in valid:
        rc = str(x["reference_defect_class"])
        pc = str(x["predicted_defect_class"])
        matrix[rc][pc] += 1
    return matrix


def aggregate_variant_metrics(scored_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute primary metrics (high+medium confidence), separate low-confidence report, stratifications, and confusion matrix."""
    primary_items = [x for x in scored_items if x["reference_confidence"] != "low"]
    low_conf_items = [x for x in scored_items if x["reference_confidence"] == "low"]

    by_solved = {
        "solved_true": _aggregate_subset([x for x in primary_items if x["reference_solved"]]),
        "solved_false": _aggregate_subset([x for x in primary_items if not x["reference_solved"]]),
    }
    by_confidence = {
        "high": _aggregate_subset([x for x in scored_items if x["reference_confidence"] == "high"]),
        "medium": _aggregate_subset([x for x in scored_items if x["reference_confidence"] == "medium"]),
    }

    classes_present = sorted({str(x["reference_defect_class"]) for x in primary_items})
    by_defect_class = {
        dc: _aggregate_subset([x for x in primary_items if x["reference_defect_class"] == dc])
        for dc in classes_present
    }

    return {
        "primary_high_medium_confidence": _aggregate_subset(primary_items),
        "low_confidence_reference_separate": _aggregate_subset(low_conf_items),
        "all_records_combined": _aggregate_subset(scored_items),
        "by_solved": by_solved,
        "by_confidence": by_confidence,
        "by_defect_class": by_defect_class,
        "confusion_matrix": build_confusion_matrix(scored_items),
        "model_errors": sum(1 for x in scored_items if x.get("model_error") is not None),
        "judge_errors": sum(1 for x in scored_items if x["judge"].get("judge_error") is not None),
    }


def evaluate_negative_controls(
    model_client: OpenAI,
    *,
    model_name: str,
    neg_records: list[dict[str, Any]],
    data_dir: Path,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Evaluate false-alarm rate (FAR) and specificity on clean/defect-free print photographs (pure visual Variant A)."""
    if not neg_records:
        return {"count": 0, "specificity_clean_rate": None, "false_alarm_rate": None, "predictions": []}

    def _run_one(rec: dict[str, Any]) -> dict[str, Any]:
        pred, err = query_model_under_test(
            model_client, model=model_name, record=rec, variant="A", data_dir=data_dir
        )
        pred_cls = pred["defect_class"] if pred is not None else None
        return {
            "id": rec["id"],
            "predicted_defect_class": pred_cls,
            "is_true_negative": pred_cls == "clean" if pred_cls is not None else None,
            "model_error": err,
        }

    workers = max(1, int(concurrency))
    if workers == 1:
        outs = [_run_one(r) for r in neg_records]
    else:
        outs_map: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, r): str(r["id"]) for r in neg_records}
            for f in as_completed(futs):
                outs_map[futs[f]] = f.result()
        outs = [outs_map[str(r["id"])] for r in neg_records]

    valid = [o for o in outs if o["model_error"] is None]
    n = len(valid)
    tn = sum(1 for o in valid if o["is_true_negative"])
    return {
        "count": n,
        "excluded_errors": len(outs) - n,
        "specificity_clean_rate": round(tn / n, 4) if n > 0 else None,
        "false_alarm_rate": round((n - tn) / n, 4) if n > 0 else None,
        "predictions": outs,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Format structured evaluation results into a concise Markdown report."""
    lines = [
        "# 3D-Print Failure Diagnosis Evaluation Report",
        "",
        f"- **Generated at**: `{report['generated_at']}`",
        f"- **Dataset**: `{report['dataset_path']}` (`{report['records_evaluated']}` positive defect records)",
        f"- **Model under test**: `{report['model_under_test']}` (`{report['base_url']}`)",
        f"- **Judge model**: `{report['judge_model']}` (`{report['judge_base_url']}`)",
        "",
        "## Headline Results (High & Medium Confidence References)",
        "",
        "| Variant | Input Provided | N | Strict Exact | Closed-Tax (`!=other`) | Synonym-Collapsed | Coarse Group | Causes (0-2) | Fixes (0-2) | Errors Excluded |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    desc_map = {
        "A": "Pure Visual-only (image(s) ONLY — zero text/title)",
        "T": "Telemetry-only (image(s) + Klipper/slicer specs — zero title/body)",
        "B": "Context-assisted (image(s) + title + specs + body_excerpt)",
    }
    for var_name, vdata in report["variants"].items():
        prim = vdata["primary_high_medium_confidence"]
        acc = f"{prim['exact_match_accuracy'] * 100:.1f}%" if prim["exact_match_accuracy"] is not None else "N/A"
        cls_acc = (
            f"{prim['closed_taxonomy_accuracy'] * 100:.1f}% ({prim['closed_taxonomy_count']})"
            if prim.get("closed_taxonomy_accuracy") is not None
            else "N/A"
        )
        syn = f"{prim['synonym_collapsed_accuracy'] * 100:.1f}%" if prim["synonym_collapsed_accuracy"] is not None else "N/A"
        crs = f"{prim['coarse_group_accuracy'] * 100:.1f}%" if prim["coarse_group_accuracy"] is not None else "N/A"
        cs = f"{prim['causes_score_mean']:.2f}" if prim["causes_score_mean"] is not None else "N/A"
        fs = f"{prim['fixes_score_mean']:.2f}" if prim["fixes_score_mean"] is not None else "N/A"
        lines.append(
            f"| **{var_name}** | {desc_map.get(var_name, var_name)} | {prim['count']} | {acc} | {cls_acc} | {syn} | {crs} | {cs} | {fs} | {prim['excluded_errors']} |"
        )

    pw = report.get("pairwise_ab")
    if isinstance(pw, dict) and pw.get("by_variant"):
        lines.extend(
            [
                "",
                f"## Blind Pairwise A/B Judge (`{pw['model_x']}` vs `{pw['model_y']}`)",
                "",
                f"| Variant | N | `{pw['model_x']}` Wins | `{pw['model_y']}` Wins | Ties | `{pw['model_x']}` Causes/Fixes | `{pw['model_y']}` Causes/Fixes |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for var_name, pdata in pw["by_variant"].items():
            if pdata["count"] == 0:
                continue
            lines.append(
                f"| **{var_name}** | {pdata['count']} | {pdata['model_x_wins']} ({pdata['model_x_win_rate'] * 100:.1f}%) "
                f"| {pdata['model_y_wins']} ({pdata['model_y_win_rate'] * 100:.1f}%) | {pdata['ties']} "
                f"| {pdata['model_x_causes_mean']:.2f} / {pdata['model_x_fixes_mean']:.2f} "
                f"| {pdata['model_y_causes_mean']:.2f} / {pdata['model_y_fixes_mean']:.2f} |"
            )

    neg = report.get("negative_controls") or {}
    if neg.get("count", 0) > 0:
        spec = f"{neg['specificity_clean_rate'] * 100:.1f}%"
        far = f"{neg['false_alarm_rate'] * 100:.1f}%"
        lines.extend(
            [
                "",
                "## Negative Controls (Clean / Post-Fix Prints — Pure Visual)",
                "",
                f"- **Evaluated clean prints**: `{neg['count']}` | **Specificity (`clean`)**: `{spec}` | **False-Alarm Rate**: `{far}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Low-Confidence Reference Records (Reported Separately)",
            "",
            "| Variant | N | Strict Exact | Synonym-Collapsed | Causes (0-2) | Fixes (0-2) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for var_name, vdata in report["variants"].items():
        low = vdata["low_confidence_reference_separate"]
        acc = f"{low['exact_match_accuracy'] * 100:.1f}%" if low["exact_match_accuracy"] is not None else "N/A"
        syn = f"{low['synonym_collapsed_accuracy'] * 100:.1f}%" if low["synonym_collapsed_accuracy"] is not None else "N/A"
        cs = f"{low['causes_score_mean']:.2f}" if low["causes_score_mean"] is not None else "N/A"
        fs = f"{low['fixes_score_mean']:.2f}" if low["fixes_score_mean"] is not None else "N/A"
        lines.append(f"| **{var_name}** | {low['count']} | {acc} | {syn} | {cs} | {fs} |")

    for var_name, vdata in report["variants"].items():
        lines.extend(
            [
                "",
                f"## Variant {var_name} Stratification",
                "",
                "### By `solved` status",
                "| Stratum | N | Strict Exact | Synonym-Collapsed | Causes Mean | Fixes Mean |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for label, sdata in vdata["by_solved"].items():
            acc = f"{sdata['exact_match_accuracy'] * 100:.1f}%" if sdata["exact_match_accuracy"] is not None else "N/A"
            syn = f"{sdata['synonym_collapsed_accuracy'] * 100:.1f}%" if sdata["synonym_collapsed_accuracy"] is not None else "N/A"
            cs = f"{sdata['causes_score_mean']:.2f}" if sdata["causes_score_mean"] is not None else "N/A"
            fs = f"{sdata['fixes_score_mean']:.2f}" if sdata["fixes_score_mean"] is not None else "N/A"
            lines.append(f"| `{label}` | {sdata['count']} | {acc} | {syn} | {cs} | {fs} |")

        lines.extend(
            [
                "",
                "### By `defect_class`",
                "| Defect Class | N | Strict Exact | Synonym-Collapsed | Causes Mean | Fixes Mean |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for dc, ddata in vdata["by_defect_class"].items():
            acc = f"{ddata['exact_match_accuracy'] * 100:.1f}%" if ddata["exact_match_accuracy"] is not None else "N/A"
            syn = f"{ddata['synonym_collapsed_accuracy'] * 100:.1f}%" if ddata["synonym_collapsed_accuracy"] is not None else "N/A"
            cs = f"{ddata['causes_score_mean']:.2f}" if ddata["causes_score_mean"] is not None else "N/A"
            fs = f"{ddata['fixes_score_mean']:.2f}" if ddata["fixes_score_mean"] is not None else "N/A"
            lines.append(f"| `{dc}` | {ddata['count']} | {acc} | {syn} | {cs} | {fs} |")

    lines.append("")
    return "\n".join(lines)


def _aggregate_pairwise_ab(rows: list[dict[str, Any]], variants: list[str], model_x: str, model_y: str) -> dict[str, Any]:
    """Summarize blind head-to-head Model X vs Model Y pairwise judge results per variant."""
    by_var: dict[str, Any] = {}
    for v in variants:
        sub = [r for r in rows if r["variant"] == v and r.get("ab_error") is None]
        n = len(sub)
        if n == 0:
            by_var[v] = {"count": 0}
            continue
        x_wins = sum(1 for r in sub if r["winner"] == "model_x")
        y_wins = sum(1 for r in sub if r["winner"] == "model_y")
        ties = sum(1 for r in sub if r["winner"] == "tie")
        by_var[v] = {
            "count": n,
            "model_x_wins": x_wins,
            "model_y_wins": y_wins,
            "ties": ties,
            "model_x_win_rate": round(x_wins / n, 4),
            "model_y_win_rate": round(y_wins / n, 4),
            "model_x_causes_mean": round(sum(r["model_x_causes"] for r in sub) / n, 4),
            "model_x_fixes_mean": round(sum(r["model_x_fixes"] for r in sub) / n, 4),
            "model_y_causes_mean": round(sum(r["model_y_causes"] for r in sub) / n, 4),
            "model_y_fixes_mean": round(sum(r["model_y_fixes"] for r in sub) / n, 4),
        }
    return {"model_x": model_x, "model_y": model_y, "by_variant": by_var}


def run_evaluate(
    config: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    dataset_path: Path | None = None,
    out_dir: Path | None = None,
    model_client: OpenAI | None = None,
    judge_client: OpenAI | None = None,
    compare_model_client: OpenAI | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    api_key_env: str | None = None,
    judge_base_url_override: str | None = None,
    judge_model_override: str | None = None,
    judge_api_key_env: str | None = None,
    compare_model_override: str | None = None,
    compare_base_url_override: str | None = None,
    compare_api_key_env: str | None = None,
    predictions_b_path: Path | None = None,
    variants_override: list[str] | None = None,
    max_records: int | None = None,
    concurrency: int = 1,
    include_negative_controls: bool = True,
) -> dict[str, Any]:
    """Execute S7 evaluation harness across Variants A, T, B (+ negative controls & optional blind A/B comparison)."""
    load_environment()
    logger = logging.getLogger("failed_print_eval")

    eval_cfg = config.get("evaluation", {})
    base_url = (
        base_url_override
        or os.environ.get("EVAL_BASE_URL")
        or str(eval_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"))
    )
    model_name = (
        model_override
        or os.environ.get("EVAL_MODEL")
        or str(eval_cfg.get("model_under_test", "gemini-3.5-flash-lite"))
    )
    judge_base_url = (
        judge_base_url_override
        or os.environ.get("JUDGE_BASE_URL")
        or str(eval_cfg.get("judge_base_url", base_url))
    )
    judge_model = (
        judge_model_override
        or os.environ.get("JUDGE_MODEL")
        or str(eval_cfg.get("judge_model", "gemini-pro-latest"))
    )
    variants = [v.upper() for v in (variants_override or eval_cfg.get("variants", ["A", "T", "B"]))]
    seed = int(eval_cfg.get("random_seed", 42))

    if model_client is None:
        model_client = init_llm_client(base_url, api_key_env=api_key_env)
    if judge_client is None:
        judge_client = init_llm_client(judge_base_url, api_key_env=judge_api_key_env or api_key_env)

    ds_path = dataset_path or (data_dir / "dataset" / "eval.jsonl")
    records = read_jsonl(ds_path)
    if max_records is not None:
        records = records[:max_records]

    eval_out_dir = out_dir or (data_dir / "eval_runs")
    eval_out_dir.mkdir(parents=True, exist_ok=True)

    all_predictions: list[dict[str, Any]] = []
    by_variant: dict[str, list[dict[str, Any]]] = {v: [] for v in variants}

    work_units: list[tuple[int, dict[str, Any], str]] = []
    for idx, rec in enumerate(records, start=1):
        for variant in variants:
            work_units.append((idx, rec, variant))

    def _eval_one(unit: tuple[int, dict[str, Any], str]) -> dict[str, Any]:
        idx, rec, variant = unit
        rec_id = str(rec["id"])
        ref = rec["reference"]
        ref_dc = str(ref["defect_class"])

        pred, model_err = query_model_under_test(
            model_client,
            model=model_name,
            record=rec,
            variant=variant,
            data_dir=data_dir,
        )
        if pred is None or model_err is not None:
            entry = {
                "id": rec_id,
                "variant": variant,
                "reference_defect_class": ref_dc,
                "predicted_defect_class": None,
                "exact_match": None,
                "synonym_match": None,
                "coarse_match": None,
                "reference_confidence": ref["confidence"],
                "reference_solved": bool(ref["solved"]),
                "prediction": None,
                "judge": {"causes_score": None, "fixes_score": None, "justification": "", "judge_error": "skipped_due_to_model_error"},
                "model_error": model_err,
            }
            logger.warning("[evaluate] (%d/%d) %s [var %s] MODEL ERROR: %s", idx, len(records), rec_id, variant, model_err)
            return entry

        judge_res = score_candidate_with_rubric_judge(
            judge_client,
            judge_model=judge_model,
            record=rec,
            candidate_pred=pred,
            data_dir=data_dir,
        )
        pred_dc = str(pred["defect_class"])
        exact_match = pred_dc == ref_dc
        syn_match = canonical_defect_class(pred_dc) == canonical_defect_class(ref_dc)
        coarse_match = coarse_defect_group(pred_dc) == coarse_defect_group(ref_dc)

        entry = {
            "id": rec_id,
            "variant": variant,
            "reference_defect_class": ref_dc,
            "predicted_defect_class": pred_dc,
            "exact_match": exact_match,
            "synonym_match": syn_match,
            "coarse_match": coarse_match,
            "reference_confidence": ref["confidence"],
            "reference_solved": bool(ref["solved"]),
            "prediction": pred,
            "judge": judge_res,
            "model_error": None,
        }
        logger.info(
            "[evaluate] (%d/%d) %s [var %s] | ref=%s pred=%s exact=%s syn=%s | causes=%s fixes=%s",
            idx,
            len(records),
            rec_id,
            variant,
            ref_dc,
            pred_dc,
            exact_match,
            syn_match,
            judge_res["causes_score"],
            judge_res["fixes_score"],
        )
        return entry

    from src.common import append_jsonl

    partial_path = eval_out_dir / "predictions_partial.jsonl"
    cached_map: dict[tuple[str, str], dict[str, Any]] = {}
    if partial_path.is_file():
        for row in read_jsonl(partial_path):
            if row.get("model_error") is None and row.get("judge", {}).get("judge_error") is None:
                cached_map[(str(row["id"]), str(row["variant"]))] = row

    pending_units = [u for u in work_units if (str(u[1]["id"]), u[2]) not in cached_map]
    append_lock = threading.Lock()

    def _eval_and_ckpt(u: tuple[int, dict[str, Any], str]) -> dict[str, Any]:
        ent = _eval_one(u)
        with append_lock:
            append_jsonl(partial_path, ent)
        return ent

    workers = max(1, int(concurrency))
    ordered_map: dict[tuple[str, str], dict[str, Any]] = dict(cached_map)
    if workers == 1:
        for u in pending_units:
            ordered_map[(str(u[1]["id"]), u[2])] = _eval_and_ckpt(u)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_eval_and_ckpt, u): (str(u[1]["id"]), u[2]) for u in pending_units}
            for fut in as_completed(futs):
                ordered_map[futs[fut]] = fut.result()
    completed_entries = [ordered_map[(str(u[1]["id"]), u[2])] for u in work_units]

    for entry in completed_entries:
        by_variant[entry["variant"]].append(entry)
        all_predictions.append(entry)

    neg_summary: dict[str, Any] = {"count": 0, "specificity_clean_rate": None, "false_alarm_rate": None}
    if include_negative_controls:
        neg_path = data_dir / "dataset" / "negative_controls.jsonl"
        neg_rows = read_jsonl(neg_path)
        if max_records is not None:
            neg_rows = neg_rows[:max_records]
        if neg_rows:
            neg_summary = evaluate_negative_controls(
                model_client,
                model_name=model_name,
                neg_records=neg_rows,
                data_dir=data_dir,
                concurrency=workers,
            )

    variant_reports = {v: aggregate_variant_metrics(items) for v, items in by_variant.items()}

    # Optional blind head-to-head Model-X vs Model-Y pairwise A/B evaluation
    pairwise_summary: dict[str, Any] | None = None
    if compare_model_override or predictions_b_path:
        pred_x_map = {
            (e["id"], e["variant"]): e["prediction"]
            for e in all_predictions
            if e.get("prediction") is not None
        }
        rec_by_id = {str(r["id"]): r for r in records}
        pred_y_map: dict[tuple[str, str], dict[str, Any]] = {}
        model_y_label = compare_model_override or (
            (predictions_b_path.parent.name if predictions_b_path.stem == "predictions" else predictions_b_path.stem)
            if predictions_b_path
            else "model_y"
        )

        if predictions_b_path is not None:
            for row in read_jsonl(predictions_b_path):
                if row.get("prediction") is not None:
                    pred_y_map[(str(row["id"]), str(row["variant"]))] = row["prediction"]
        elif compare_model_override is not None:
            comp_url = compare_base_url_override or base_url
            c_client = compare_model_client or init_llm_client(comp_url, api_key_env=compare_api_key_env or api_key_env)

            def _query_y(u: tuple[int, dict[str, Any], str]) -> tuple[tuple[str, str], dict[str, Any] | None]:
                _, r_obj, var = u
                py, err_y = query_model_under_test(
                    c_client, model=compare_model_override, record=r_obj, variant=var, data_dir=data_dir
                )
                return (str(r_obj["id"]), var), (py if err_y is None else None)

            if workers == 1:
                for u in work_units:
                    k, py = _query_y(u)
                    if py is not None:
                        pred_y_map[k] = py
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for fut in as_completed([pool.submit(_query_y, u) for u in work_units]):
                        k, py = fut.result()
                        if py is not None:
                            pred_y_map[k] = py

        ab_pairs = [
            (rid, var)
            for _, rec_o, var in work_units
            for rid in [str(rec_o["id"])]
            if (rid, var) in pred_x_map and (rid, var) in pred_y_map
        ]

        def _judge_ab_one(pair: tuple[str, str]) -> dict[str, Any]:
            rid, var = pair
            local_rng = random.Random(f"{seed}:ab:{rid}:{var}")
            try:
                res = score_pairwise_blind_ab(
                    judge_client,
                    judge_model=judge_model,
                    record=rec_by_id[rid],
                    pred_model_x=pred_x_map[(rid, var)],
                    pred_model_y=pred_y_map[(rid, var)],
                    data_dir=data_dir,
                    rng=local_rng,
                )
                return {"id": rid, "variant": var, **res, "ab_error": None}
            except Exception as exc:
                return {"id": rid, "variant": var, "winner": "tie", "ab_error": str(exc)}

        if workers == 1:
            ab_rows = [_judge_ab_one(p) for p in ab_pairs]
        else:
            ab_map: dict[tuple[str, str], dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(_judge_ab_one, p): p for p in ab_pairs}
                for f in as_completed(futs):
                    ab_map[futs[f]] = f.result()
            ab_rows = [ab_map[p] for p in ab_pairs]

        write_jsonl(eval_out_dir / "pairwise_ab.jsonl", ab_rows)
        pairwise_summary = _aggregate_pairwise_ab(ab_rows, variants, model_name, model_y_label)

    report = {
        "generated_at": utc_now_iso(),
        "dataset_path": str(ds_path),
        "records_evaluated": len(records),
        "base_url": base_url,
        "model_under_test": model_name,
        "judge_base_url": judge_base_url,
        "judge_model": judge_model,
        "variants": variant_reports,
        "negative_controls": neg_summary,
        "pairwise_ab": pairwise_summary,
    }

    preds_path = eval_out_dir / "predictions.jsonl"
    report_json_path = eval_out_dir / "eval_report.json"
    report_md_path = eval_out_dir / "eval_report.md"

    write_jsonl(preds_path, all_predictions)
    if partial_path.is_file():
        partial_path.unlink()
    write_json(report_json_path, report)
    report_md_path.write_text(render_markdown_report(report), encoding="utf-8")

    logger.info("[evaluate] Saved report to %s and %s", report_json_path, report_md_path)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S7: Evaluate VLM diagnosis + rubric/A-B judge on dataset/eval.jsonl.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument("--dataset", type=Path, default=None, help="Override path to eval.jsonl")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory for eval reports")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL for model under test")
    parser.add_argument("--model", default=None, help="Model under test name")
    parser.add_argument("--api-key-env", default=None, help="Env var name for model-under-test API key")
    parser.add_argument("--judge-base-url", default=None, help="OpenAI-compatible base URL for judge model")
    parser.add_argument("--judge-model", default=None, help="Judge model name")
    parser.add_argument("--judge-api-key-env", default=None, help="Env var name for judge API key")
    parser.add_argument("--compare-model", default=None, help="Optional Model Y name for blind pairwise A/B judging")
    parser.add_argument("--compare-base-url", default=None, help="Base URL for --compare-model")
    parser.add_argument("--compare-api-key-env", default=None, help="Env var name for --compare-model API key")
    parser.add_argument("--predictions-b", type=Path, default=None, help="Existing predictions.jsonl for blind A/B comparison")
    parser.add_argument("--variants", nargs="+", choices=["A", "T", "B", "a", "t", "b"], default=None, help="Variants to run")
    parser.add_argument("--max-records", type=int, default=None, help="Limit number of dataset records evaluated")
    parser.add_argument("--concurrency", type=int, default=4, help="Parallel worker threads for LLM calls")
    parser.add_argument("--no-negative-controls", action="store_true", help="Skip negative_controls.jsonl check")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    run_evaluate(
        config,
        data_dir=args.data_dir,
        dataset_path=args.dataset,
        out_dir=args.out_dir,
        base_url_override=args.base_url,
        model_override=args.model,
        api_key_env=args.api_key_env,
        judge_base_url_override=args.judge_base_url,
        judge_model_override=args.judge_model,
        judge_api_key_env=args.judge_api_key_env,
        compare_model_override=args.compare_model,
        compare_base_url_override=args.compare_base_url,
        compare_api_key_env=args.compare_api_key_env,
        predictions_b_path=args.predictions_b,
        variants_override=args.variants,
        max_records=args.max_records,
        concurrency=args.concurrency,
        include_negative_controls=not args.no_negative_controls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
