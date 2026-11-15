"""Shared utilities: environment loading, Context.dev client init, request_id & credit tracking, and file I/O."""

from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import mimetypes
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from context.dev import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ContextDev,
    ContextDevError,
)
from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "queries.yaml"
DEFAULT_LEXICON_PATH = PROJECT_ROOT / "config" / "lexicon.txt"
DEFAULT_SCHEMA_DIR = PROJECT_ROOT / "config" / "schema"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

DEFECT_TAXONOMY: tuple[str, ...] = (
    "stringing",
    "oozing",
    "warping",
    "layer_shift",
    "underextrusion",
    "overextrusion",
    "bed_adhesion",
    "first_layer",
    "spaghetti_detection",
    "z_banding",
    "ringing",
    "blobs_zits",
    "cracking",
    "pillowing",
    "ghosting",
    "overhang_curling",
    "mechanical_misalignment",
    "other",
)

# Collapses exact physical synonyms in the 17-class taxonomy
SYNONYM_COLLAPSE_MAP: dict[str, str] = {
    "ringing": "ringing_ghosting",
    "ghosting": "ringing_ghosting",
    "stringing": "stringing_oozing",
    "oozing": "stringing_oozing",
}

# Collapses overlapping boundary families in addition to exact synonyms
COARSE_GROUP_MAP: dict[str, str] = {
    **SYNONYM_COLLAPSE_MAP,
    "first_layer": "first_layer_adhesion_warping",
    "bed_adhesion": "first_layer_adhesion_warping",
    "warping": "first_layer_adhesion_warping",
}


def canonical_defect_class(defect_class: str) -> str:
    """Collapse synonymous defect classes (ringing/ghosting, stringing/oozing)."""
    dc = defect_class.strip().lower()
    return SYNONYM_COLLAPSE_MAP.get(dc, dc)


def coarse_defect_group(defect_class: str) -> str:
    """Collapse synonymous and overlapping boundary classes (e.g. first_layer/bed_adhesion/warping)."""
    dc = defect_class.strip().lower()
    return COARSE_GROUP_MAP.get(dc, dc)


def encode_image_as_data_url(image_path: Path) -> str:
    """Encode a local image file as a base64 data URL for OpenAI-compatible vision chat."""
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime or not mime.startswith("image/"):
        ext = image_path.suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else (ext or 'jpeg')}"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class MissingCredentialsError(RuntimeError):
    """Raised when a required API key is absent from the environment."""


class BudgetExceededError(RuntimeError):
    """Raised when a pipeline run reaches max_requests_per_run."""


class FatalContextAPIError(RuntimeError):
    """Raised on unrecoverable Context.dev auth, permission, or credit-exhaustion errors."""


_SECRET_PATTERN = re.compile(r"(ctxt_secret_[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+)")


def redact_secrets(text: str) -> str:
    """Mask any accidental token patterns before logging."""
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def load_environment(dotenv_path: Path | None = None) -> None:
    """Load .env from the project root without overriding existing process env vars."""
    path = dotenv_path or (PROJECT_ROOT / ".env")
    if path.is_file():
        load_dotenv(dotenv_path=path, override=False)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logging cleanly and return package logger."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore2").setLevel(logging.WARNING)
    return logging.getLogger("failed_print_eval")


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load YAML configuration file."""
    path = config_path or DEFAULT_CONFIG_PATH
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration at {path} must be a YAML mapping")
    return data


def make_record_id(subreddit: str, post_id: str) -> str:
    """Build canonical record identifier (e.g., fixmyprint_1abcde)."""
    clean_sub = re.sub(r"[^a-z0-9]+", "", subreddit.lower())
    clean_id = re.sub(r"[^a-z0-9_]+", "", post_id.lower())
    return f"{clean_sub}_{clean_id}"


def init_context_client(
    config: dict[str, Any] | None = None,
    *,
    max_retries_override: int | None = None,
    timeout_override: float | None = None,
) -> ContextDev:
    """Initialize the Context.dev SDK client using CONTEXT_DEV_API_KEY from the environment."""
    load_environment()
    api_key = os.environ.get("CONTEXT_DEV_API_KEY", "").strip()
    if not api_key:
        raise MissingCredentialsError(
            "CONTEXT_DEV_API_KEY is not set. Set it in your environment or in an ignored .env file."
        )

    cost_cfg = (config or {}).get("cost_control", {})
    timeout_sec = float(
        timeout_override if timeout_override is not None else cost_cfg.get("sdk_timeout_sec", 95.0)
    )
    max_retries = int(
        max_retries_override if max_retries_override is not None else cost_cfg.get("sdk_max_retries", 2)
    )
    return ContextDev(api_key=api_key, timeout=timeout_sec, max_retries=max_retries)


def resolve_llm_api_key(explicit_env_var: str | None = None) -> str:
    """Resolve OpenAI-compatible LLM API key from environment without exposing secret values."""
    load_environment()
    candidates = (
        [explicit_env_var]
        if explicit_env_var
        else ["LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]
    )
    for var_name in candidates:
        if not var_name:
            continue
        val = os.environ.get(var_name, "").strip()
        if val:
            return val
    joined = ", ".join(c for c in candidates if c)
    raise MissingCredentialsError(
        f"No LLM API key found in environment (checked: {joined}). Set it in .env or environment."
    )


def init_llm_client(
    base_url: str,
    *,
    api_key_env: str | None = None,
    timeout_sec: float = 120.0,
) -> OpenAI:
    """Initialize an OpenAI-compatible client (supports Mistral, OpenAI, Gemini, vLLM, etc.)."""
    api_key = resolve_llm_api_key(api_key_env)
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec, max_retries=2)


@dataclass
class RunTracker:
    """Tracks Context.dev requests, request_ids, and credit consumption for a pipeline stage."""

    stage: str
    max_requests: int = 250
    data_dir: Path = DEFAULT_DATA_DIR
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("failed_print_eval"))
    requests_made: int = 0
    credits_consumed: int = 0
    last_credits_remaining: int | None = None
    request_ids: list[str] = field(default_factory=list)
    failed_requests: int = 0

    def check_budget(self, upcoming_requests: int = 1) -> None:
        """Raise BudgetExceededError if executing upcoming_requests would exceed max_requests."""
        if self.requests_made + upcoming_requests > self.max_requests:
            raise BudgetExceededError(
                f"[{self.stage}] Hard cap max_requests_per_run={self.max_requests} reached "
                f"(requests_made={self.requests_made},credits_consumed={self.credits_consumed})."
            )

    def record_response(self, response: Any, *, operation: str, target: str = "") -> tuple[str | None, int]:
        """Extract and log request_id and key_metadata credits from a Context.dev SDK response."""
        self.requests_made += 1
        request_id: str | None = None
        consumed = 0
        remaining: int | None = None

        if isinstance(response, dict):
            request_id = response.get("request_id")
            km = response.get("key_metadata") or {}
            if isinstance(km, dict):
                consumed = int(km.get("credits_consumed") or 0)
                rem_val = km.get("credits_remaining")
                remaining = int(rem_val) if rem_val is not None else None
        else:
            request_id = getattr(response, "request_id", None)
            km = getattr(response, "key_metadata", None)
            if km is not None:
                consumed = int(getattr(km, "credits_consumed", 0) or 0)
                rem_val = getattr(km, "credits_remaining", None)
                remaining = int(rem_val) if rem_val is not None else None

        self.credits_consumed += consumed
        if remaining is not None:
            self.last_credits_remaining = remaining
        if request_id:
            self.request_ids.append(request_id)

        self.logger.info(
            "[%s] %s | request_id=%s | credits_consumed=%d | run_credits=%d | credits_remaining=%s | target=%s",
            self.stage,
            operation,
            request_id or "unknown",
            consumed,
            self.credits_consumed,
            remaining if remaining is not None else "unknown",
            target,
        )

        usage_log_path = self.data_dir / "credit_usage.jsonl"
        append_jsonl(
            usage_log_path,
            {
                "timestamp": utc_now_iso(),
                "stage": self.stage,
                "operation": operation,
                "target": target,
                "request_id": request_id,
                "credits_consumed": consumed,
                "credits_remaining": remaining,
            },
        )
        return request_id, consumed

    def handle_sdk_error(self, exc: ContextDevError, *, operation: str, target: str = "") -> dict[str, Any]:
        """Log structured details from a Context.dev SDK exception; raise on fatal auth/billing errors."""
        self.requests_made += 1
        self.failed_requests += 1

        status_code: int | None = getattr(exc, "status_code", None)
        request_id: str | None = getattr(exc, "request_id", None)
        body: Any = getattr(exc, "body", None)
        error_code: str | None = None
        error_data: Any = None

        if isinstance(body, dict):
            error_code = body.get("error_code") or body.get("code")
            error_data = body.get("error_data")
            if not request_id and isinstance(body.get("request_id"), str):
                request_id = body["request_id"]

        safe_msg = redact_secrets(str(exc))
        self.logger.error(
            "[%s] %s FAILED | status=%s | error_code=%s | request_id=%s | target=%s | detail=%s",
            self.stage,
            operation,
            status_code,
            error_code,
            request_id or "unknown",
            target,
            safe_msg,
        )

        info = {
            "status_code": status_code,
            "error_code": error_code,
            "request_id": request_id,
            "error_data": error_data,
            "message": safe_msg,
        }

        if isinstance(exc, APIStatusError) and status_code in {401, 402, 403}:
            raise FatalContextAPIError(
                f"Unrecoverable Context.dev error (status={status_code}, error_code={error_code}, "
                f"request_id={request_id}): {safe_msg}"
            ) from exc

        if isinstance(exc, (APITimeoutError, APIConnectionError, APIStatusError)):
            return info
        return info

    def log_summary(self) -> dict[str, Any]:
        """Log and return stage execution summary."""
        summary = {
            "stage": self.stage,
            "requests_made": self.requests_made,
            "failed_requests": self.failed_requests,
            "credits_consumed": self.credits_consumed,
            "credits_remaining": self.last_credits_remaining,
        }
        self.logger.info(
            "[%s] Run complete | requests=%d | failed=%d | credits_consumed=%d | credits_remaining=%s",
            self.stage,
            self.requests_made,
            self.failed_requests,
            self.credits_consumed,
            self.last_credits_remaining if self.last_credits_remaining is not None else "unknown",
        )
        return summary


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON file."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    """Atomically write pretty-printed UTF-8 JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp_path.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL file into list of dicts (returns [] if file does not exist)."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_no}")
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Atomically write iterable of dicts as JSONL; returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            count += 1
    tmp_path.replace(path)
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Append a single JSON object line to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False))
        fh.write("\n")


def parse_image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Extract (width, height) from PNG, JPEG, GIF, or WebP image header bytes using stdlib."""
    if len(data) < 16:
        return None, None

    # PNG: 8-byte signature + IHDR chunk length(4) + 'IHDR'(4) + width(4) + height(4)
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)

    # GIF87a / GIF89a
    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)

    # WebP (RIFF....WEBP)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk_type = data[12:16]
        if chunk_type == b"VP8 " and len(data) >= 30:
            width, height = struct.unpack("<HH", data[26:30])
            return int(width & 0x3FFF), int(height & 0x3FFF)
        if chunk_type == b"VP8L" and len(data) >= 25:
            bits = struct.unpack("<I", data[21:25])[0]
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return int(width), int(height)
        if chunk_type == b"VP8X" and len(data) >= 30:
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return int(width), int(height)

    # JPEG: scan markers until SOF0..SOF15 (excluding DHT 0xC4, JPG 0xC8, DAC 0xCC)
    if data[:2] == b"\xff\xd8":
        idx = 2
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3,
            0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB,
            0xCD, 0xCE, 0xCF,
        }
        length = len(data)
        while idx < length - 1:
            if data[idx] != 0xFF:
                idx += 1
                continue
            while idx < length and data[idx] == 0xFF:
                idx += 1
            if idx >= length:
                break
            marker = data[idx]
            idx += 1
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7) or marker == 0x01:
                continue
            if idx + 2 > length:
                break
            seg_len = struct.unpack(">H", data[idx : idx + 2])[0]
            if seg_len < 2 or idx + seg_len > length:
                break
            if marker in sof_markers and seg_len >= 7:
                height, width = struct.unpack(">HH", data[idx + 3 : idx + 7])
                return int(width), int(height)
            idx += seg_len

    return None, None
