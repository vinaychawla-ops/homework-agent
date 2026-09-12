"""Docling-backed OCR for the homework evaluator.

Two paths, matching the product design:

- **Printed / scanned documents** -> Docling's standard pipeline
  (:func:`extract_printed`). Local OCR, no API key needed.
- **Handwritten homework photos** -> Docling's VLM pipeline pointed at an
  OpenAI-compatible endpoint (:func:`transcribe_handwriting`). Configured for
  OpenRouter + Google's free Gemma model; the API key comes from the
  ``OPENROUTER_API_KEY`` environment variable and is never logged or stored.

:func:`transcribe_image` picks the right path: ``"vlm"`` forces handwriting
mode, ``"docling"`` forces the standard pipeline, and ``"auto"`` (default)
uses the VLM path when an OpenRouter key is configured, falling back to the
standard pipeline otherwise.
"""

from __future__ import annotations

import logging
import os
import random
import re
import tempfile
import time
from typing import Optional

DEFAULT_VLM_MODEL = "google/gemma-4-31b-it:free"
#: Fallback models OpenRouter tries in order when the primary 429s or its
#: provider is saturated (sent as the `models` array; OpenRouter reroutes
#: within the same request). Override with OPENROUTER_FALLBACK_MODELS as a
#: comma-separated list; set it empty to disable fallbacks.
DEFAULT_FALLBACK_MODELS = [
    "google/gemma-4-26b-a4b-it:free",
    "inclusionai/ling-3.0-flash-vl:free",
]
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Longest image side (px) sent to the VLM. Docling re-encodes the image as a
#: full-resolution PNG data URL, so a 12MP phone photo becomes a 20-50MB JSON
#: payload and the API rejects it with HTTP 413. Downscaling keeps handwriting
#: legible while staying well under request-size limits.
VLM_MAX_IMAGE_SIDE = 1568

#: Env vars consulted by this module.
ENV_API_KEY = "OPENROUTER_API_KEY"
ENV_MODEL = "OPENROUTER_MODEL"
ENV_FALLBACK_MODELS = "OPENROUTER_FALLBACK_MODELS"
ENV_IMAGE_MODE = "OCR_IMAGE_MODE"

_HANDWRITING_PROMPT = (
    "Transcribe the handwritten homework visible in this image. "
    "Output each answer on its own line in the format `Q1: <answer>`, "
    "`Q2: <answer>`, and so on - one answer per line, separated by newlines. "
    "Transcribe exactly what is written - do not solve, correct, "
    "or explain anything. If a question has no visible answer, output the "
    "question id followed by a colon and nothing else. "
    "Output only the transcription, no commentary."
)


class OCRError(Exception):
    """Raised when OCR/transcription fails in a way the caller should surface."""


def docling_available() -> bool:
    """True when the ``docling`` package is importable."""
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def _require_docling() -> None:
    if not docling_available():
        raise OCRError(
            "Docling is not installed. Install it with: pip install -r requirements.txt"
        )


def _api_key() -> Optional[str]:
    return os.environ.get(ENV_API_KEY) or None


def image_mode(explicit: Optional[str] = None) -> str:
    """Resolve the effective image OCR mode: 'auto' | 'docling' | 'vlm'."""
    mode = (explicit or os.environ.get(ENV_IMAGE_MODE) or "auto").lower()
    if mode not in ("auto", "docling", "vlm"):
        raise ValueError(f"Unknown OCR image mode {mode!r}; expected auto|docling|vlm")
    return mode


def extract_printed(path: str) -> str:
    """Extract text from a printed/scanned PDF or image with Docling's standard pipeline."""
    _require_docling()
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(path)
    text = result.document.export_to_markdown()
    if not text or not text.strip():
        raise OCRError(f"Docling extracted no text from {path!r}.")
    return text


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg and "limit" in msg or "rate-limited" in msg


class _DoclingApiErrorCapture(logging.Handler):
    """Captures the HTTP status docling logs when its VLM API call fails.

    Docling's api_image_request() retries 429/5xx internally and then logs
    "Error calling the API. status=<code> ..." and returns an empty result
    instead of raising. This handler recovers the status so the caller can
    tell a rate limit apart from an empty transcription. If docling ever
    changes its log format, no status is captured and the generic
    no-transcription error is used (graceful degradation).
    """

    def __init__(self) -> None:
        super().__init__()
        self.last_status: Optional[int] = None

    def emit(self, record: logging.LogRecord) -> None:
        match = re.search(r"Error calling the API\.\s*status=(\d+)", record.getMessage())
        if match:
            self.last_status = int(match.group(1))


def _rate_limit_message(image_path: str, detail: object) -> str:
    return (
        f"Handwriting transcription for {image_path!r} kept hitting "
        f"the free model's rate limit ({detail}). The shared free pool "
        f"is busy - wait a few minutes and retry, or add credit / "
        f"your own provider key at "
        f"https://openrouter.ai/settings/integrations."
    )


def _backoff_sleep(base: float, attempt: int) -> None:
    """Sleep with exponential backoff plus jitter before a 429 retry.

    (Docling's API layer swallows the 429 into an empty result, so the
    response's Retry-After header never reaches us; jittered backoff is the
    mitigation available at this layer.)
    """
    time.sleep(base * (2 ** attempt) * random.uniform(0.8, 1.25))


def _vlm_model_list(primary: str) -> list[str]:
    """Primary model plus fallbacks, de-duplicated, primary first."""
    raw = os.environ.get(ENV_FALLBACK_MODELS)
    if raw is None:
        fallbacks = list(DEFAULT_FALLBACK_MODELS)
    else:
        fallbacks = [m.strip() for m in raw.split(",") if m.strip()]
    seen: set[str] = set()
    models: list[str] = []
    for m in [primary, *fallbacks]:
        if m and m not in seen:
            seen.add(m)
            models.append(m)
    return models


def _downscale_for_vlm(image_path: str) -> str:
    """Return a path to a VLM-sized copy of the image.

    Returns ``image_path`` unchanged when it already fits within
    :data:`VLM_MAX_IMAGE_SIDE` or cannot be opened (downstream code keeps
    its existing error behavior); otherwise writes a resized PNG temp file
    (the caller deletes it when it differs from ``image_path``).
    """
    from PIL import Image

    try:
        img = Image.open(image_path)
        img.load()
    except Exception:
        return image_path
    w, h = img.size
    longest = max(w, h)
    if longest <= VLM_MAX_IMAGE_SIDE:
        return image_path
    scale = VLM_MAX_IMAGE_SIDE / longest
    resized = img.convert("RGB").resize(
        (round(w * scale), round(h * scale)), Image.LANCZOS
    )
    fd, dest = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    resized.save(dest, "PNG")
    return dest


def transcribe_handwriting(
    image_path: str,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 240,
    max_retries: int = 3,
) -> str:
    """Transcribe handwritten homework via Docling's VLM pipeline + OpenRouter.

    Sends the page image to the OpenAI-compatible chat-completions endpoint
    with ``google/gemma-4-31b-it:free`` (override with ``OPENROUTER_MODEL``).
    Retries transient rate limits (HTTP 429 from the free shared pool) with
    exponential backoff before giving up with an :class:`OCRError`.
    """
    _require_docling()
    key = api_key or _api_key()
    if not key:
        raise OCRError(
            f"Handwriting transcription needs an OpenRouter API key: set the "
            f"{ENV_API_KEY} environment variable (get one at "
            f"https://openrouter.ai/keys)."
        )
    chosen_model = model or os.environ.get(ENV_MODEL) or DEFAULT_VLM_MODEL
    # OpenRouter tries these in order within a single request when the
    # primary 429s or its provider is saturated.
    vlm_models = _vlm_model_list(chosen_model)
    model_params: dict = (
        {"models": vlm_models}
        if len(vlm_models) > 1
        else {"model": chosen_model}
    )

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.datamodel.pipeline_options_vlm_model import (
        ApiVlmOptions,
        ResponseFormat,
    )
    from docling.document_converter import (
        DocumentConverter,
        ImageFormatOption,
        PdfFormatOption,
    )
    from docling.pipeline.vlm_pipeline import VlmPipeline

    vlm_options = ApiVlmOptions(
        url=OPENROUTER_CHAT_COMPLETIONS_URL,
        params=dict(model_params, max_tokens=4096, temperature=0.0),
        headers={"Authorization": f"Bearer {key}"},
        prompt=_HANDWRITING_PROMPT,
        response_format=ResponseFormat.MARKDOWN,
        timeout=timeout,
    )
    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_options,
        enable_remote_services=True,  # mandatory: gates any outbound HTTP
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.IMAGE: ImageFormatOption(
                pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
            ),
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
            ),
        }
    )

    # Shrink phone photos before docling re-encodes them as full-resolution
    # PNG data URLs (a 12MP photo becomes a 20-50MB payload -> HTTP 413).
    work_path = _downscale_for_vlm(image_path)
    try:
        return _transcribe_handwriting_attempts(
            converter, work_path, image_path, max_retries
        )
    finally:
        if work_path != image_path:
            try:
                os.remove(work_path)
            except OSError:
                pass


def _transcribe_handwriting_attempts(
    converter, work_path: str, image_path: str, max_retries: int
) -> str:
    """Run the VLM transcription with retry/backoff; see transcribe_handwriting."""
    for attempt in range(max_retries + 1):
        capture = _DoclingApiErrorCapture()
        api_logger = logging.getLogger("docling.utils.api_image_request")
        api_logger.addHandler(capture)
        try:
            result = converter.convert(work_path)
            text = result.document.export_to_markdown()
        except OCRError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_rate_limit_error(exc) and attempt < max_retries:
                _backoff_sleep(10, attempt)  # ~10s, ~20s, ~40s + jitter
                continue
            if _is_rate_limit_error(exc):
                raise OCRError(_rate_limit_message(image_path, exc)) from exc
            raise OCRError(
                f"Handwriting transcription failed for {image_path!r}: {exc}"
            ) from exc
        finally:
            api_logger.removeHandler(capture)

        if text and text.strip():
            return text

        # Empty result: docling's API layer already retried 429/5xx internally
        # and gave up. Use the captured HTTP status to explain why.
        status = capture.last_status
        if status == 429:
            if attempt < max_retries:
                _backoff_sleep(15, attempt)  # ~15s, ~30s, ~60s + jitter
                continue
            raise OCRError(_rate_limit_message(image_path, f"HTTP {status}"))
        if status == 401:
            raise OCRError(
                f"Handwriting transcription for {image_path!r} was rejected "
                f"(HTTP 401): the OpenRouter API key was missing or invalid."
            )
        if status:
            raise OCRError(
                f"Handwriting transcription for {image_path!r} failed: the "
                f"VLM API returned HTTP {status}."
            )
        raise OCRError(
            f"The VLM returned no transcription for {image_path!r}."
        )


def transcribe_image(path: str, *, mode: Optional[str] = None) -> str:
    """Transcribe a homework photo/scan, picking Docling path by mode.

    ``mode`` is ``"auto"`` (VLM handwriting when an OpenRouter key is set,
    otherwise the standard pipeline), ``"vlm"``, or ``"docling"``.
    """
    resolved = image_mode(mode)
    if resolved == "vlm" or (resolved == "auto" and _api_key()):
        return transcribe_handwriting(path)
    return extract_printed(path)
