"""Tests for ocr.py. Docling is stubbed out; no network, no models."""

import sys
import types

import pytest

from homework_agent import ocr


class _FakeDocument:
    def __init__(self, text):
        self._text = text

    def export_to_markdown(self):
        return self._text


class _FakeResult:
    def __init__(self, text):
        self.document = _FakeDocument(text)


class _FakeConverter:
    """Stand-in for docling's DocumentConverter."""

    behavior = staticmethod(lambda path: "Q1: stubbed")
    seen_format_options = None

    def __init__(self, format_options=None):
        _FakeConverter.seen_format_options = format_options

    def convert(self, path):
        return _FakeResult(_FakeConverter.behavior(path))


CAPTURED = {}


def _install_docling_stub(monkeypatch):
    def _api_opts(**kw):
        CAPTURED["api_opts"] = kw
        return kw

    def _pipeline_opts(**kw):
        CAPTURED["pipeline_opts"] = kw
        return kw

    mods = {}
    mods["docling"] = types.ModuleType("docling")
    mods["docling.datamodel"] = types.ModuleType("docling.datamodel")
    mods["docling.pipeline"] = types.ModuleType("docling.pipeline")

    dc = types.ModuleType("docling.document_converter")
    dc.DocumentConverter = _FakeConverter
    dc.ImageFormatOption = lambda **kw: ("image", kw)
    dc.PdfFormatOption = lambda **kw: ("pdf", kw)
    mods["docling.document_converter"] = dc

    bm = types.ModuleType("docling.datamodel.base_models")
    bm.InputFormat = types.SimpleNamespace(IMAGE="image", PDF="pdf")
    mods["docling.datamodel.base_models"] = bm

    po = types.ModuleType("docling.datamodel.pipeline_options")
    po.VlmPipelineOptions = _pipeline_opts
    mods["docling.datamodel.pipeline_options"] = po

    vm = types.ModuleType("docling.datamodel.pipeline_options_vlm_model")
    vm.ApiVlmOptions = _api_opts
    vm.ResponseFormat = types.SimpleNamespace(MARKDOWN="markdown")
    mods["docling.datamodel.pipeline_options_vlm_model"] = vm

    vp = types.ModuleType("docling.pipeline.vlm_pipeline")
    vp.VlmPipeline = type("VlmPipeline", (), {})
    mods["docling.pipeline.vlm_pipeline"] = vp

    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def stub_docling(monkeypatch):
    _install_docling_stub(monkeypatch)
    CAPTURED.clear()
    _FakeConverter.behavior = staticmethod(lambda path: "Q1: stubbed")
    _FakeConverter.seen_format_options = None
    for var in (ocr.ENV_API_KEY, ocr.ENV_MODEL, ocr.ENV_FALLBACK_MODELS, ocr.ENV_IMAGE_MODE):
        monkeypatch.delenv(var, raising=False)
    return _FakeConverter


# --- mode resolution -------------------------------------------------------

def test_image_mode_default_auto(stub_docling):
    assert ocr.image_mode() == "auto"


def test_image_mode_env_override(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_IMAGE_MODE, "vlm")
    assert ocr.image_mode() == "vlm"


def test_image_mode_explicit_wins(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_IMAGE_MODE, "docling")
    assert ocr.image_mode("vlm") == "vlm"


def test_image_mode_invalid(stub_docling):
    with pytest.raises(ValueError, match="Unknown OCR image mode"):
        ocr.image_mode("handwriting")


# --- routing ---------------------------------------------------------------

def test_transcribe_image_vlm_when_key_set(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    assert ocr.transcribe_image("/tmp/x.png") == "Q1: stubbed"
    assert CAPTURED["api_opts"]["params"]["models"] == [
        ocr.DEFAULT_VLM_MODEL,
        *ocr.DEFAULT_FALLBACK_MODELS,
    ]


def test_transcribe_image_docling_without_key(stub_docling):
    assert ocr.transcribe_image("/tmp/x.png") == "Q1: stubbed"
    assert "api_opts" not in CAPTURED  # standard pipeline, no VLM options


def test_transcribe_image_explicit_vlm_needs_key(stub_docling):
    with pytest.raises(ocr.OCRError, match=ocr.ENV_API_KEY):
        ocr.transcribe_image("/tmp/x.png", mode="vlm")


def test_transcribe_image_explicit_docling_ignores_key(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    assert ocr.transcribe_image("/tmp/x.png", mode="docling") == "Q1: stubbed"
    assert "api_opts" not in CAPTURED


# --- handwriting path ------------------------------------------------------

def test_transcribe_handwriting_requires_key(stub_docling):
    with pytest.raises(ocr.OCRError, match=ocr.ENV_API_KEY):
        ocr.transcribe_handwriting("/tmp/x.png")


def test_transcribe_handwriting_config(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    monkeypatch.setenv(ocr.ENV_MODEL, "some/model:free")
    assert ocr.transcribe_handwriting("/tmp/x.png") == "Q1: stubbed"
    assert CAPTURED["api_opts"]["url"] == ocr.OPENROUTER_CHAT_COMPLETIONS_URL
    params = CAPTURED["api_opts"]["params"]
    assert params["models"] == ["some/model:free", *ocr.DEFAULT_FALLBACK_MODELS]
    assert "model" not in params
    assert CAPTURED["api_opts"]["headers"] == {"Authorization": "Bearer k"}
    assert CAPTURED["pipeline_opts"]["enable_remote_services"] is True
    assert _FakeConverter.seen_format_options is not None


def test_transcribe_handwriting_single_model_param_without_fallbacks(
    stub_docling, monkeypatch
):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    monkeypatch.setenv(ocr.ENV_FALLBACK_MODELS, "")
    assert ocr.transcribe_handwriting("/tmp/x.png") == "Q1: stubbed"
    params = CAPTURED["api_opts"]["params"]
    assert params["model"] == ocr.DEFAULT_VLM_MODEL
    assert "models" not in params


def test_transcribe_handwriting_retries_rate_limit(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    calls = {"n": 0, "sleeps": []}
    monkeypatch.setattr(ocr.time, "sleep", lambda s: calls["sleeps"].append(s))

    def behavior(path):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("provider error 429 upstream")
        return "Q1: recovered"

    _FakeConverter.behavior = staticmethod(behavior)
    assert ocr.transcribe_handwriting("/tmp/x.png", max_retries=3) == "Q1: recovered"
    assert calls["n"] == 3
    # jittered backoff: 10 * 2^attempt * uniform(0.8, 1.25)
    assert 8.0 <= calls["sleeps"][0] <= 12.5
    assert 16.0 <= calls["sleeps"][1] <= 25.0


def test_backoff_sleep_applies_jitter(stub_docling, monkeypatch):
    sleeps = []
    monkeypatch.setattr(ocr.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(ocr.random, "uniform", lambda a, b: 1.0)
    ocr._backoff_sleep(10, 2)
    assert sleeps == [40.0]


def test_vlm_model_list_defaults(stub_docling):
    assert ocr._vlm_model_list("primary/m") == [
        "primary/m",
        *ocr.DEFAULT_FALLBACK_MODELS,
    ]


def test_vlm_model_list_env_override(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_FALLBACK_MODELS, "a/b, c/d ")
    assert ocr._vlm_model_list("primary/m") == ["primary/m", "a/b", "c/d"]


def test_vlm_model_list_env_empty_disables(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_FALLBACK_MODELS, "")
    assert ocr._vlm_model_list("primary/m") == ["primary/m"]


def test_vlm_model_list_dedupes_primary(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_FALLBACK_MODELS, "primary/m, other/n")
    assert ocr._vlm_model_list("primary/m") == ["primary/m", "other/n"]


def test_transcribe_handwriting_gives_up_after_retries(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    monkeypatch.setattr(ocr.time, "sleep", lambda s: None)
    _FakeConverter.behavior = staticmethod(
        lambda path: (_ for _ in ()).throw(RuntimeError("429 busy"))
    )
    with pytest.raises(ocr.OCRError, match="rate limit"):
        ocr.transcribe_handwriting("/tmp/x.png", max_retries=1)


def test_transcribe_handwriting_non_retryable_error(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    _FakeConverter.behavior = staticmethod(
        lambda path: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(ocr.OCRError, match="transcription failed"):
        ocr.transcribe_handwriting("/tmp/x.png")


def test_transcribe_handwriting_empty_result(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    _FakeConverter.behavior = staticmethod(lambda path: "   ")
    with pytest.raises(ocr.OCRError, match="no transcription"):
        ocr.transcribe_handwriting("/tmp/x.png")


def _log_api_error(status: int):
    import logging

    logging.getLogger("docling.utils.api_image_request").error(
        "Error calling the API. status=%s content_type=application/json response='{}'",
        status,
    )


def test_transcribe_handwriting_rate_limit_empty_result_retries(
    stub_docling, monkeypatch
):
    """Docling swallows HTTP errors into empty results; a logged 429 still retries."""
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    calls = {"n": 0, "sleeps": []}
    monkeypatch.setattr(ocr.time, "sleep", lambda s: calls["sleeps"].append(s))

    def behavior(path):
        calls["n"] += 1
        if calls["n"] < 3:
            _log_api_error(429)
            return ""
        return "Q1: recovered"

    _FakeConverter.behavior = staticmethod(behavior)
    assert ocr.transcribe_handwriting("/tmp/x.png", max_retries=3) == "Q1: recovered"
    assert calls["n"] == 3
    # jittered backoff: 15 * 2^attempt * uniform(0.8, 1.25)
    assert 12.0 <= calls["sleeps"][0] <= 18.75
    assert 24.0 <= calls["sleeps"][1] <= 37.5


def test_transcribe_handwriting_rate_limit_empty_result_gives_up(
    stub_docling, monkeypatch
):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")
    monkeypatch.setattr(ocr.time, "sleep", lambda s: None)

    def behavior(path):
        _log_api_error(429)
        return ""

    _FakeConverter.behavior = staticmethod(behavior)
    with pytest.raises(ocr.OCRError, match="rate limit"):
        ocr.transcribe_handwriting("/tmp/x.png", max_retries=1)


def test_transcribe_handwriting_unauthorized_empty_result(stub_docling, monkeypatch):
    monkeypatch.setenv(ocr.ENV_API_KEY, "k")

    def behavior(path):
        _log_api_error(401)
        return ""

    _FakeConverter.behavior = staticmethod(behavior)
    with pytest.raises(ocr.OCRError, match="401"):
        ocr.transcribe_handwriting("/tmp/x.png", max_retries=0)


# --- standard pipeline -----------------------------------------------------

def test_extract_printed_uses_docling(stub_docling):
    assert ocr.extract_printed("/tmp/x.pdf") == "Q1: stubbed"


def test_extract_printed_empty_result(stub_docling):
    _FakeConverter.behavior = staticmethod(lambda path: "")
    with pytest.raises(ocr.OCRError, match="no text"):
        ocr.extract_printed("/tmp/x.pdf")


def test_extract_printed_without_docling(monkeypatch):
    monkeypatch.setattr(ocr, "docling_available", lambda: False)
    with pytest.raises(ocr.OCRError, match="Docling is not installed"):
        ocr.extract_printed("/tmp/x.pdf")


def test_is_rate_limit_error():
    assert ocr._is_rate_limit_error(RuntimeError("HTTP 429"))
    assert ocr._is_rate_limit_error(RuntimeError("rate-limited upstream"))
    assert not ocr._is_rate_limit_error(RuntimeError("boom"))
