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
import re
import time
from typing import Optional

DEFAULT_VLM_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Env vars consulted by this module.
ENV_API_KEY = "OPENROUTER_API_KEY"
ENV_MODEL = "OPENROUTER_MODEL"
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
        params=dict(model=chosen_model, max_tokens=4096, temperature=0.0),
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

    for attempt in range(max_retries + 1):
        capture = _DoclingApiErrorCapture()
        api_logger = logging.getLogger("docling.utils.api_image_request")
        api_logger.addHandler(capture)
        try:
            result = converter.convert(image_path)
            text = result.document.export_to_markdown()
        except OCRError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_rate_limit_error(exc) and attempt < max_retries:
                time.sleep(10 * (2 ** attempt))  # 10s, 20s, 40s
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
                time.sleep(15 * (2 ** attempt))  # 15s, 30s, 60s
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
