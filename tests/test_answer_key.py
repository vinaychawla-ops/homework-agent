"""Tests for teacher-uploaded answer keys (answer_key.py) and the custom
assignment store (assignments.py additions). Docling/network paths are not
exercised; image transcription is covered by production E2E."""

import json
import os

import pytest

from homework_agent import answer_key, assignments
from homework_agent.answer_key import KeyQuestion


def test_infer_question_type_shapes():
    assert answer_key.infer_question_type("b") == "multiple_choice"
    assert answer_key.infer_question_type("(C)") == "multiple_choice"
    assert answer_key.infer_question_type("3/4") == "numeric"
    assert answer_key.infer_question_type("0.75") == "numeric"
    assert answer_key.infer_question_type("x^2 + 5x + 6") == "expression"
    assert answer_key.infer_question_type("2x+6=14") == "expression"
    assert answer_key.infer_question_type("evaporation") == "short_answer"
    assert (
        answer_key.infer_question_type("water heats up and rises")
        == "short_answer"
    )


def test_parse_plain_ocr_key():
    headers, questions = answer_key.parse_key_text("Q1: 3/4\nQ2: b\n")
    assert headers == {}
    assert [(q.qid, q.question_type, q.answer) for q in questions] == [
        ("Q1", "numeric", "3/4"),
        ("Q2", "multiple_choice", "b"),
    ]
    assert all(q.type_inferred for q in questions)
    assert questions[0].explanation == "The correct answer is 3/4."


def test_parse_structured_key():
    text = """# comment
Title: Fractions Quiz
Subject: math
Teacher: Jane Doe <jane@school.edu>

Q1 [numeric] Simplify 6/8 || 3/4 || Divide top and bottom by 2
Q2 [multiple_choice] Which is 2^3? (a) 6 (b) 8 (c) 9 || b || || points: 2
Q3 [short_answer] Explain evaporation || water heats and rises || || concepts: heat, rises
"""
    headers, questions = answer_key.parse_key_text(text)
    assert headers == {
        "title": "Fractions Quiz",
        "subject": "math",
        "teacher": "Jane Doe <jane@school.edu>",
    }
    by_id = {q.qid: q for q in questions}
    assert by_id["Q1"].prompt == "Simplify 6/8"
    assert by_id["Q1"].answer == "3/4"
    assert by_id["Q1"].explanation == "Divide top and bottom by 2"
    assert not by_id["Q1"].type_inferred
    assert by_id["Q2"].points == 2.0
    assert by_id["Q3"].key_concepts == ["heat", "rises"]
    assert by_id["Q3"].points == 1.0


def test_parse_structured_infers_missing_type():
    _, questions = answer_key.parse_key_text("Q1 || b\n")
    assert questions[0].question_type == "multiple_choice"
    assert questions[0].type_inferred


def test_parse_structured_empty_answer_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        answer_key.parse_key_text("Q1 [numeric] || \n")


def test_render_round_trip():
    text = (
        "Title: Quiz\nSubject: science\n\n"
        "Q1 [numeric] || 3/4 ||\n"
        "Q2 [multiple_choice] || b || || points: 2\n"
    )
    headers, questions = answer_key.parse_key_text(text)
    rendered = answer_key.render_key_text(headers, questions)
    headers2, questions2 = answer_key.parse_key_text(rendered)
    assert headers2 == headers
    assert [(q.qid, q.question_type, q.answer, q.points) for q in questions2] == [
        (q.qid, q.question_type, q.answer, q.points) for q in questions
    ]


def test_validate_key_errors():
    assert answer_key.validate_key({}, []) != []
    errors = answer_key.validate_key({"title": "T", "subject": "history"}, [])
    assert any("math" in e and "science" in e for e in errors)
    dup = [
        KeyQuestion("Q1", "a", "numeric"),
        KeyQuestion("Q1", "b", "numeric"),
    ]
    errors = answer_key.validate_key({"title": "T", "subject": "math"}, dup)
    assert any("Duplicate" in e for e in errors)
    bad_type = [KeyQuestion("Q1", "a", "essay")]
    errors = answer_key.validate_key({"title": "T", "subject": "math"}, bad_type)
    assert any("unknown type" in e for e in errors)


def test_validate_key_ok():
    qs = [KeyQuestion("Q1", "3/4", "numeric")]
    assert answer_key.validate_key({"title": "T", "subject": "math"}, qs) == []


def test_parse_teacher_header():
    assert answer_key.parse_teacher_header("Jane Doe <jane@school.edu>") == (
        "Jane Doe",
        "jane@school.edu",
    )
    assert answer_key.parse_teacher_header("Jane Doe") == ("Jane Doe", "")


def test_extract_key_text_plain(tmp_path):
    path = tmp_path / "key.txt"
    path.write_text("Q1: 3/4\nQ2: b\n")
    assert answer_key.extract_key_text(str(path)) == "Q1: 3/4\nQ2: b\n"


def test_extract_key_text_docx(tmp_path):
    docx = pytest.importorskip("docx")
    path = str(tmp_path / "key.docx")
    doc = docx.Document()
    doc.add_paragraph("Q1: 3/4")
    doc.add_paragraph("Q2: b")
    doc.save(path)
    text = answer_key.extract_key_text(path)
    assert "Q1: 3/4" in text
    assert "Q2: b" in text


def test_extract_key_text_legacy_doc_rejected(tmp_path):
    path = tmp_path / "key.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(ValueError, match="[Ll]egacy .doc"):
        answer_key.extract_key_text(str(path), "key.doc")


def test_extract_key_text_empty_rejected(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n")
    with pytest.raises(ValueError, match="no text"):
        answer_key.extract_key_text(str(path))


# --- custom assignment store ---


@pytest.fixture
def custom_dir(tmp_path, monkeypatch):
    directory = str(tmp_path / "assignments")
    monkeypatch.setenv(assignments.ASSIGNMENTS_DIR_ENV, directory)
    return directory


def _sample_questions():
    return [
        KeyQuestion("Q1", "3/4", "numeric", prompt="Simplify 6/8"),
        KeyQuestion("Q2", "b", "multiple_choice", prompt="Pick b"),
    ]


def test_build_save_load_round_trip(custom_dir):
    built = assignments.build_assignment(
        _sample_questions(),
        title="Fractions Quiz",
        subject="math",
        teacher_name="Jane Doe",
        teacher_email="jane@school.edu",
    )
    assert built.id.startswith("custom-fractions-quiz")
    path = assignments.save_assignment(built)
    assert os.path.exists(path)
    loaded = assignments.load_custom_assignments()
    assert built.id in loaded
    again = loaded[built.id]
    assert again.title == "Fractions Quiz"
    assert [q.id for q in again.questions] == ["Q1", "Q2"]
    assert again.questions[0].correct_answer == "3/4"
    assert again.teacher_email == "jane@school.edu"


def test_unique_assignment_id_dedupes(custom_dir):
    first = assignments.build_assignment(
        _sample_questions(), title="Quiz", subject="math"
    )
    assignments.save_assignment(first)
    second_id = assignments.unique_assignment_id("Quiz")
    assert second_id != first.id
    assert second_id.startswith(first.id)


def test_title_in_use(custom_dir):
    assert not assignments.title_in_use("Fractions Quiz")
    assignments.save_assignment(
        assignments.build_assignment(
            _sample_questions(), title="Fractions Quiz", subject="math"
        )
    )
    assert assignments.title_in_use("fractions quiz")  # case-insensitive


def test_resolve_and_get_find_custom(custom_dir):
    built = assignments.build_assignment(
        _sample_questions(), title="Fractions Quiz", subject="math"
    )
    assignments.save_assignment(built)
    assert assignments.get_assignment(built.id).title == "Fractions Quiz"
    assert assignments.resolve_assignment("fractions quiz").id == built.id
    assert assignments.resolve_assignment("Quiz").id == built.id


def test_corrupt_json_skipped(custom_dir):
    os.makedirs(custom_dir, exist_ok=True)
    with open(os.path.join(custom_dir, "bad.json"), "w") as fh:
        fh.write("{not json")
    # built-ins still load fine
    assert "math-fractions-01" in assignments.all_assignments()


def test_custom_assignment_graded_against_its_key(custom_dir):
    from homework_agent import grading

    built = assignments.build_assignment(
        _sample_questions(), title="Fractions Quiz", subject="math"
    )
    assignments.save_assignment(built)
    sheet = grading.grade_submission(built, {"Q1": "3/4", "Q2": "a"})
    assert sheet.evaluations[0].is_correct
    assert not sheet.evaluations[1].is_correct
    assert sheet.evaluations[1].correct_answer == "b"


def test_detect_assignment_finds_custom(custom_dir):
    built = assignments.build_assignment(
        [
            KeyQuestion(
                "Q1",
                "photosynthesis",
                "short_answer",
                prompt="Describe photosynthesis in green plants",
            )
        ],
        title="Plant Biology",
        subject="science",
    )
    assignments.save_assignment(built)
    found = assignments.detect_assignment(
        "Q1: photosynthesis happens in green plants with chlorophyll"
    )
    assert found is not None
    assert found.id == built.id
