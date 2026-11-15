"""One-command end-to-end pipeline runner (S1 discover -> S7 evaluate)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from src.build_dataset import run_build_dataset
from src.common import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_LEXICON_PATH,
    DEFAULT_SCHEMA_DIR,
    load_config,
    setup_logging,
    utc_now_iso,
    write_json,
)
from src.discover import run_discovery
from src.download import run_download
from src.evaluate import run_evaluate
from src.fetch import run_fetch
from src.filter import run_filter
from src.synthesize import run_synthesize

ALL_STAGES: tuple[str, ...] = (
    "discover",
    "fetch",
    "filter",
    "download",
    "synthesize",
    "build",
    "evaluate",
)


def run_pipeline(
    config: dict[str, Any],
    *,
    stages: list[str] | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    schema_dir: Path = DEFAULT_SCHEMA_DIR,
    subreddits: list[str] | None = None,
    max_queries: int | None = None,
    pilot_size: int | None = None,
    force_batch: bool = False,
    classify_images: bool = False,
    max_images_per_post: int | None = None,
    final_release: bool = False,
    max_eval_records: int | None = None,
    max_requests: int | None = None,
) -> dict[str, Any]:
    """Execute selected stages sequentially, persisting intermediate artifacts on disk."""
    logger = logging.getLogger("failed_print_eval")
    active_stages = stages or list(ALL_STAGES)
    results: dict[str, Any] = {"started_at": utc_now_iso(), "stages": {}}

    for stage in active_stages:
        logger.info("========== Starting stage: %s ==========", stage)
        if stage == "discover":
            results["stages"]["discover"] = run_discovery(
                config,
                data_dir=data_dir,
                subreddits_override=subreddits,
                max_queries=max_queries,
                max_candidates=pilot_size * 2 if pilot_size else None,
                max_requests_override=max_requests,
            )
        elif stage == "fetch":
            results["stages"]["fetch"] = run_fetch(
                config,
                data_dir=data_dir,
                max_threads=pilot_size,
                force_batch=force_batch,
                max_requests_override=max_requests,
            )
        elif stage == "filter":
            results["stages"]["filter"] = run_filter(
                config,
                data_dir=data_dir,
                lexicon_path=lexicon_path,
                classify_images=True if classify_images else None,
                max_requests_override=max_requests,
            )
        elif stage == "download":
            results["stages"]["download"] = run_download(
                config,
                data_dir=data_dir,
                max_posts=pilot_size,
                max_images_per_post_override=max_images_per_post,
                max_requests_override=max_requests,
            )
        elif stage == "synthesize":
            results["stages"]["synthesize"] = run_synthesize(
                config,
                data_dir=data_dir,
                schema_dir=schema_dir,
                max_threads=pilot_size,
            )
        elif stage == "build":
            results["stages"]["build"] = run_build_dataset(
                config,
                data_dir=data_dir,
                schema_dir=schema_dir,
                final_release=final_release,
            )
        elif stage == "evaluate":
            results["stages"]["evaluate"] = run_evaluate(
                config,
                data_dir=data_dir,
                max_records=max_eval_records,
            )
        else:
            raise ValueError(f"Unknown stage {stage!r}; choose from {ALL_STAGES}")

    results["completed_at"] = utc_now_iso()
    write_json(data_dir / "pipeline_summary.json", results)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run S1..S7 3D-print failure eval pipeline.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to queries.yaml")
    parser.add_argument("--lexicon", type=Path, default=DEFAULT_LEXICON_PATH, help="Path to lexicon.txt")
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR, help="Path to schema directory")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to data directory")
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=list(ALL_STAGES),
        default=None,
        help="Subset of stages to execute in order (default: all S1..S7)",
    )
    parser.add_argument("--skip-evaluate", action="store_true", help="Run S1..S6 without S7 evaluation")
    parser.add_argument("--subreddits", nargs="+", default=None, help="Override discovery subreddits")
    parser.add_argument("--max-queries", type=int, default=None, help="Limit discovery queries per subreddit")
    parser.add_argument("--pilot-size", type=int, default=None, help="Cap threads fetched/downloaded/synthesized")
    parser.add_argument("--batch", action="store_true", help="Force batch mode in S2 fetch")
    parser.add_argument("--classify-images", action="store_true", help="Enable online photography image filter in S3")
    parser.add_argument("--max-images-per-post", type=int, default=None, help="Max images downloaded per post in S4")
    parser.add_argument("--final-release", action="store_true", help="Assign 100%% of records to test split in S6")
    parser.add_argument("--max-eval-records", type=int, default=None, help="Cap records evaluated in S7")
    parser.add_argument("--max-requests", type=int, default=None, help="Per-stage Context.dev request hard cap")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_level)
    config = load_config(args.config)
    stages = args.stages
    if stages is None and args.skip_evaluate:
        stages = [s for s in ALL_STAGES if s != "evaluate"]

    run_pipeline(
        config,
        stages=stages,
        data_dir=args.data_dir,
        lexicon_path=args.lexicon,
        schema_dir=args.schema_dir,
        subreddits=args.subreddits,
        max_queries=args.max_queries,
        pilot_size=args.pilot_size,
        force_batch=args.batch,
        classify_images=args.classify_images,
        max_images_per_post=args.max_images_per_post,
        final_release=args.final_release,
        max_eval_records=args.max_eval_records,
        max_requests=args.max_requests,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
