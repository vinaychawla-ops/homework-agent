"""Tests for submission.py: text / PDF / image answer extraction."""

import pytest

from homework_agent.models import Submission
from homework_agent.submission import extract_answers, parse_image, parse_pdf, parse_text

from conftest import sample_path


def test_parse_text_basic():
    answers = parse_text("Q1: 3/4\nQ2: x = 4\nQ3: b")
    assert answers == {"Q1": "3/4", "Q2": "x = 4", "Q3": "b"}


def test_parse_text_case_insensitive_and_separators():
    answers = parse_text("q1 - 3/4\nQ2) hello world\n  Q3.  (b)  ")
    assert answers == {"Q1": "3/4", "Q2": "hello world", "Q3": "(b)"}


def test_parse_text_ignores_noise_lines():
    answers = parse_text("Name: Alex\nDate: today\nQ1: 42\nsome random note")
    assert answers == {"Q1": "42"}


def test_parse_text_empty():
    assert parse_text("") == {}
    assert parse_text("no answers here") == {}


def test_parse_text_multiple_answers_on_one_line():
    # VLM transcriptions sometimes run answers together on one line.
    answers = parse_text("Q1: b Q2: x = 4 Q3: (c)")
    assert answers == {"Q1": "b", "Q2": "x = 4", "Q3": "(c)"}


def test_parse_text_single_line_vlm_style():
    answers = parse_text(
        "Q1: b Q2: The sun heats the puddle Q3: condensation Q4: a"
    )
    assert answers["Q1"] == "b"
    assert answers["Q2"] == "The sun heats the puddle"
    assert answers["Q3"] == "condensation"
    assert answers["Q4"] == "a"


def test_parse_text_noise_after_last_answer_ignored():
    assert parse_text("Q1: 42\nsome random note") == {"Q1": "42"}


def test_parse_pdf_sample():
    answers = parse_pdf(sample_path("math_homework.pdf"))
    assert answers["Q1"] == "2/3"
    assert answers["Q2"] == "x = 5"
    assert answers["Q5"] == "3/8 is left."


def test_parse_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_pdf("/nonexistent/homework.pdf")


def test_parse_pdf_text_layer_skips_ocr(monkeypatch):
    def _fail(path):
        raise AssertionError("Docling OCR should not run when the text layer works")

    monkeypatch.setattr("homework_agent.ocr.extract_printed", _fail)
    answers = parse_pdf(sample_path("math_homework.pdf"))
    assert answers["Q1"] == "2/3"


def test_parse_pdf_scanned_falls_back_to_docling_ocr(monkeypatch, tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path = str(tmp_path / "scan.pdf")
    with open(pdf_path, "wb") as f:
        writer.write(f)

    monkeypatch.setattr(
        "homework_agent.ocr.extract_printed", lambda path: "Q1: 7"
    )
    assert parse_pdf(pdf_path) == {"Q1": "7"}


def test_parse_image_with_transcription():
    answers = parse_image(
        sample_path("science_homework.png"),
        "Q1: b\nQ2: the water evaporates",
    )
    assert answers == {"Q1": "b", "Q2": "the water evaporates"}


def test_parse_image_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_image("/nonexistent/photo.png", "Q1: b")


def test_parse_image_blank_transcription_runs_ocr(monkeypatch):
    """Blank transcription -> Docling OCR path (mocked, no network)."""
    monkeypatch.setattr(
        "homework_agent.ocr.transcribe_image",
        lambda path, mode=None: "Q1: b\nQ2: x = 4",
    )
    answers = parse_image(sample_path("science_homework.png"), "   ")
    assert answers == {"Q1": "b", "Q2": "x = 4"}


def test_parse_image_without_transcription_runs_ocr(monkeypatch):
    monkeypatch.setattr(
        "homework_agent.ocr.transcribe_image",
        lambda path, mode=None: "Q3: c",
    )
    answers = parse_image(sample_path("science_homework.png"))
    assert answers == {"Q3": "c"}


def test_parse_image_supplied_transcription_skips_ocr(monkeypatch):
    def _fail(*a, **k):
        raise AssertionError("OCR should not run when transcription is supplied")

    monkeypatch.setattr("homework_agent.ocr.transcribe_image", _fail)
    answers = parse_image(sample_path("science_homework.png"), "Q1: b")
    assert answers == {"Q1": "b"}


def test_parse_image_ocr_mode_forwarded(monkeypatch):
    seen = {}

    def _fake(path, mode=None):
        seen["mode"] = mode
        return "Q1: a"

    monkeypatch.setattr("homework_agent.ocr.transcribe_image", _fake)
    parse_image(sample_path("science_homework.png"), ocr_mode="vlm")
    assert seen["mode"] == "vlm"


def test_extract_answers_dispatches_text():
    sub = Submission("A", "a@x.edu", "math-fractions-01", "text", "Q1: 1")
    assert extract_answers(sub) == {"Q1": "1"}


def test_extract_answers_dispatches_pdf():
    sub = Submission("B", "b@x.edu", "math-fractions-01", "pdf", sample_path("math_homework.pdf"))
    assert extract_answers(sub)["Q3"] == "a"


def test_extract_answers_dispatches_image():
    sub = Submission(
        "P", "p@x.edu", "sci-water-cycle-01", "image",
        sample_path("science_homework.png"), transcribed_text="Q4: a",
    )
    assert extract_answers(sub) == {"Q4": "a"}


def test_extract_answers_fallback_single_question_unlabeled_text():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "A rainbow forms when sunlight shines through rain drops.")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "A rainbow forms when sunlight shines through rain drops."}


def test_extract_answers_fallback_not_used_when_labels_parse():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text", "Q1: b")
    assert extract_answers(sub, fallback_question_id="Q1") == {"Q1": "b"}


def test_extract_answers_fallback_needs_nonblank_text():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text", "   ")
    assert extract_answers(sub, fallback_question_id="Q1") == {}


def test_extract_answers_no_fallback_by_default():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "A rainbow forms when sunlight shines through rain drops.")
    assert extract_answers(sub) == {}


def test_extract_answers_fallback_mislabeled_question_number():
    # Regression: the VLM can misread "Q1" as "Q17:" (production 2026-09-13:
    # auto-mode transcription parsed to {"Q17": ...}, Q1 scored zero with
    # "(no answer provided)"). The single-question fallback must remap it.
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q17: When you have rain and shine at the same time.")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "When you have rain and shine at the same time."}


def test_extract_answers_fallback_mislabeled_joins_multiple():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q2: rain and shine\nQ9: sunlight through drops")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "rain and shine sunlight through drops"}


def test_extract_answers_fallback_blank_primary_uses_other_answers():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q1:   \nQ3: sunlight through rain drops")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "sunlight through rain drops"}


def test_extract_answers_no_remap_for_multi_question_assignment():
    # Multi-question assignments never remap: a "Q9:" label stays Q9.
    sub = Submission("A", "a@x.edu", "sci-water-cycle-01", "text",
                     "Q9: evaporation")
    assert extract_answers(sub) == {"Q9": "evaporation"}


# --- Answer labels ("Ans:", "Answer:", "A<n>:") — production 2026-09-14 ---
# A student's photo ("Q. How is Rainbow created in the sky? / Ans: Due to
# rain.") was transcribed with the question line labeled Q1; the parser took
# the question text as the answer and dropped the "Ans:" line, so the email
# showed "Student answer: Q. How is Rainbow created in the sky?".

def test_parse_text_ans_label_attaches_to_current_question():
    answers = parse_text(
        "Q1: Q. How is Rainbow created in the sky?\nAns: Due to rain.")
    assert answers == {"Q1": "Due to rain."}


def test_parse_text_answer_label_word():
    answers = parse_text("Q1: What is 2+2?\nAnswer: 4")
    assert answers == {"Q1": "4"}


def test_parse_text_a_number_label_maps_to_question():
    # Student writes only the answer, labeled "A1:".
    assert parse_text("A1: Due to rain.") == {"Q1": "Due to rain."}
    assert parse_text("Q1: 3/4\nA2: x = 4") == {"Q1": "3/4", "Q2": "x = 4"}


def test_parse_text_ans_and_question_on_one_line():
    assert parse_text("Q1: What is 2+2? Ans: 4") == {"Q1": "4"}


def test_parse_text_ans_label_does_not_split_plain_words():
    # "trans:" contains "ans:" but must not split the line.
    assert parse_text("Q1: trans:mit the signal") == {"Q1": "trans:mit the signal"}


def test_extract_answers_unclaimed_ans_label_used_by_fallback():
    # "Ans:" with no question line at all: the single-question fallback
    # still attributes it (without the "Ans:" prefix).
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Ans: Due to rain.")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "Due to rain."}


def test_extract_answers_question_echo_discarded():
    # Transcription holds only the question: the echo guard drops it so the
    # grader reports "(no answer provided)" instead of scoring the question
    # against itself ("rain" matching inside "Rainbow" scored 0.33).
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q. How is Rainbow created in the sky?")
    assert extract_answers(
        sub,
        fallback_question_id="Q1",
        question_prompts={"Q1": "How is a rainbow created in the sky?"},
    ) == {}


def test_extract_answers_real_answer_survives_echo_guard():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q1: Q. How is Rainbow created in the sky?\nAns: Due to rain.")
    assert extract_answers(
        sub,
        fallback_question_id="Q1",
        question_prompts={"Q1": "How is a rainbow created in the sky?"},
    ) == {"Q1": "Due to rain."}


def test_extract_answers_echo_guard_ignores_legitimate_restatement():
    # A real answer that restates part of the question is not an echo.
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "Q1: A rainbow is created when sunlight shines through raindrops.")
    assert extract_answers(
        sub,
        fallback_question_id="Q1",
        question_prompts={"Q1": "How is a rainbow created in the sky?"},
    ) == {"Q1": "A rainbow is created when sunlight shines through raindrops."}


def _rainbow_sub(text):
    return Submission("A", "a@x.edu", "sci-rainbows-01", "text", text)


_RAINBOW_PROMPT = {"Q1": "How is a rainbow created in the sky?"}


def test_extract_answers_answer_before_question_line():
    # VLM transcribed the "Ans:" line before the question line: the answer
    # must still be attributed instead of reporting "no answer provided".
    sub = _rainbow_sub("Ans: Due to rain.\nQ1: Q. How is Rainbow created in the sky?")
    assert extract_answers(
        sub, fallback_question_id="Q1", question_prompts=_RAINBOW_PROMPT
    ) == {"Q1": "Due to rain."}


def test_extract_answers_unlabeled_answer_line():
    # The answer sits on its own line with no label at all: the residual
    # (transcription minus the question echo) becomes the answer.
    sub = _rainbow_sub("Q1: Q. How is Rainbow created in the sky?\nDue to rain.")
    assert extract_answers(
        sub, fallback_question_id="Q1", question_prompts=_RAINBOW_PROMPT
    ) == {"Q1": "Due to rain."}


def test_extract_answers_bare_a_label():
    # A bare "A:" is an answer label too.
    sub = _rainbow_sub("Q1: Q. How is Rainbow created in the sky?\nA: Due to rain.")
    assert extract_answers(
        sub, fallback_question_id="Q1", question_prompts=_RAINBOW_PROMPT
    ) == {"Q1": "Due to rain."}


def test_extract_answers_echo_with_no_residual_stays_empty():
    # Question only, no answer anywhere: still "no answer provided",
    # the residual must not resurrect the question itself.
    sub = _rainbow_sub("Q1: Q. How is Rainbow created in the sky?")
    assert extract_answers(
        sub, fallback_question_id="Q1", question_prompts=_RAINBOW_PROMPT
    ) == {}


def test_extract_answers_residual_drops_echo_keeps_answer():
    # Echo and answer on separate unlabeled lines: only the answer survives.
    sub = _rainbow_sub(
        "How is Rainbow created in the sky?\nIt is due to rain I think."
    )
    assert extract_answers(
        sub, fallback_question_id="Q1", question_prompts=_RAINBOW_PROMPT
    ) == {"Q1": "It is due to rain I think."}


def test_extract_answers_residual_without_prompt_uses_raw_text():
    # No question prompts available: keep the old raw-text fallback.
    sub = _rainbow_sub("Some handwritten response without any labels.")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "Some handwritten response without any labels."}


def test_parse_text_bare_a_attaches_to_current_question():
    assert parse_text("Q1: something\nA: Due to rain.") == {"Q1": "Due to rain."}


def test_parse_text_bare_a_word_not_a_label():
    # A bare word "a" is never treated as an answer label.
    assert parse_text("Q1: a rainbow forms after rain") == {
        "Q1": "a rainbow forms after rain"}
