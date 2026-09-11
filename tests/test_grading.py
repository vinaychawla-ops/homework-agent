"""Tests for grading.py: math equivalence, science rubrics, explanations."""

import pytest

from homework_agent.grading import grade_question, grade_submission
from homework_agent.models import Question


def q(**overrides):
    base = dict(
        id="Q1", subject="math", prompt="p",
        question_type="numeric", correct_answer="4",
        correct_explanation="because.",
    )
    base.update(overrides)
    return Question(**base)


# --- numeric ---------------------------------------------------------------

def test_numeric_exact_match():
    ev = grade_question(q(), "4")
    assert ev.is_correct and ev.points_earned == 1.0 and ev.explanation == ""


def test_numeric_accepts_fraction_and_decimal_forms():
    assert grade_question(q(correct_answer="3/4"), "0.75").is_correct
    assert grade_question(q(correct_answer="0.5"), "1/2").is_correct
    assert grade_question(q(correct_answer="4"), "x = 4").is_correct


def test_numeric_wrong_value():
    ev = grade_question(q(), "5")
    assert not ev.is_correct
    assert ev.points_earned == 0.0
    assert "5" in ev.explanation and "4" in ev.explanation
    assert ev.correct_explanation == "because."


def test_numeric_tolerance():
    ev = grade_question(q(correct_answer="3.14159", tolerance=0.01), "3.14")
    assert ev.is_correct


def test_numeric_garbage_answer():
    ev = grade_question(q(), "banana")
    assert not ev.is_correct
    assert "not a recognizable number" in ev.explanation


# --- expression ------------------------------------------------------------

def test_expression_equivalent_forms():
    question = q(question_type="expression", correct_answer="x^2 + 5x + 6")
    assert grade_question(question, "x**2+5*x+6").is_correct
    assert grade_question(question, "6 + 5x + x^2").is_correct


def test_expression_wrong():
    question = q(question_type="expression", correct_answer="x^2 + 5x + 6")
    ev = grade_question(question, "x^2 + 6x + 5")
    assert not ev.is_correct
    assert "not algebraically equivalent" in ev.explanation


# --- multiple choice -------------------------------------------------------

def test_multiple_choice_case_insensitive():
    question = q(question_type="multiple_choice", correct_answer="b")
    assert grade_question(question, "B").is_correct
    assert grade_question(question, "(b)").is_correct


def test_multiple_choice_wrong():
    question = q(question_type="multiple_choice", correct_answer="b")
    ev = grade_question(question, "a")
    assert not ev.is_correct
    assert "(a)" in ev.explanation and "(b)" in ev.explanation


# --- short answer ----------------------------------------------------------

def short_q(**overrides):
    base = dict(
        question_type="short_answer",
        correct_answer="Water evaporates into vapor.",
        correct_explanation="Heat turns liquid into vapor.",
        key_concepts=["heat", "evaporat", "water vapor"],
        points=2.0,
    )
    base.update(overrides)
    return q(**base)


def test_short_answer_all_concepts_correct():
    ev = grade_question(short_q(), "Heat gives energy so water evaporates into water vapor.")
    assert ev.is_correct
    assert ev.points_earned == 2.0


def test_short_answer_partial_credit_and_missing_listed():
    ev = grade_question(short_q(), "The water evaporates.")
    assert not ev.is_correct
    assert 0 < ev.points_earned < 2.0
    assert "heat" in ev.explanation  # missing concept is named


def test_short_answer_nothing_relevant():
    ev = grade_question(short_q(), "I like pizza.")
    assert not ev.is_correct
    assert ev.points_earned == 0.0


def test_short_answer_single_concept_question():
    ev = grade_question(short_q(key_concepts=["condensation"]), "Condensation happens.")
    assert ev.is_correct


# --- missing answers & full submission -------------------------------------

def test_missing_answer_scores_zero_with_explanation():
    ev = grade_question(q(), None)
    assert not ev.is_correct
    assert ev.student_answer == "(no answer provided)"
    assert "No answer was provided" in ev.explanation


def test_blank_answer_scores_zero():
    ev = grade_question(q(), "   ")
    assert not ev.is_correct and ev.points_earned == 0.0


def test_grade_submission_marks_unanswered_wrong(math_assignment):
    sheet = grade_submission(math_assignment, {"Q1": "3/4"})
    assert len(sheet.evaluations) == 5
    assert sheet.evaluations[0].is_correct
    assert all(not e.is_correct for e in sheet.evaluations[1:])
    assert sheet.total_earned == pytest.approx(1.0)


def test_grade_submission_all_correct_science(science_assignment):
    answers = {
        "Q1": "b",
        "Q2": "The sun's heat gives water energy so it evaporates into water vapor.",
        "Q3": "condensation",
        "Q4": "a",
    }
    sheet = grade_submission(science_assignment, answers)
    assert sheet.correct_count == 4
    assert sheet.percentage == pytest.approx(100.0)
