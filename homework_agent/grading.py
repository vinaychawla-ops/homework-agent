"""Deterministic grading engine for Math and Science homework (demo, offline).

Math:
  - numeric:         exact/fraction/decimal equivalence within tolerance
  - expression:      symbolic equivalence via sympy when available,
                     otherwise normalized string comparison
  - multiple_choice: case-insensitive letter match

Science / short answers (both subjects):
  - short_answer:    key-concept coverage; correct when the fraction of
                     required concepts present >= question.pass_threshold,
                     with proportional partial credit otherwise.

Every miss produces two explanations: why the student's answer is wrong and
an explanation of the correct answer (taken from the answer key).
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Dict, Optional

from .models import AnswerEvaluation, Assignment, GradedSheet, Question

try:  # optional but recommended; listed in requirements.txt
    import sympy as _sympy
except ImportError:  # pragma: no cover
    _sympy = None


# ---------------------------------------------------------------------------
# normalisation helpers
# ---------------------------------------------------------------------------

def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _strip_answer_prefix(value: str) -> str:
    """Remove leading 'x =' style prefixes students often include."""
    cleaned = value.strip()
    cleaned = re.sub(r"^[a-zA-Z]\s*=\s*", "", cleaned)
    return cleaned


def _as_number(value: str) -> Optional[float]:
    """Parse ints, decimals, fractions ('3/4') and percentages ('75%')."""
    text = _strip_answer_prefix(value).replace(",", "").strip()
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# per-type graders: each returns (is_correct, score_fraction, wrong_explanation)
# ---------------------------------------------------------------------------

def _grade_numeric(question: Question, student: str) -> tuple[bool, float, str]:
    expected = _as_number(question.correct_answer)
    got = _as_number(student)
    if expected is None:  # answer key is malformed; fail closed, never crash
        return False, 0.0, "The answer key for this question is invalid; flagged for teacher review."
    if got is None:
        return False, 0.0, (
            f"Your answer {student!r} is not a recognizable number. "
            f"The correct answer is {question.correct_answer}."
        )
    if abs(got - expected) <= question.tolerance:
        return True, 1.0, ""
    return False, 0.0, (
        f"Your answer evaluates to {got:g}, but the correct value is "
        f"{question.correct_answer} (evaluates to {expected:g})."
    )


def _normalise_expression(expr: str) -> str:
    text = _strip_answer_prefix(expr).lower().replace(" ", "")
    # normalise power notation idempotently: "**" -> "^" -> "**"
    text = text.replace("**", "^").replace("^", "**")
    text = text.replace("·", "*").replace("×", "*")
    # implicit multiplication: "5x" -> "5*x", ")(" -> ")*("
    text = re.sub(r"(?<=\d)(?=[a-zA-Z\(])", "*", text)
    text = re.sub(r"(?<=\))(?=[a-zA-Z\d\(])", "*", text)
    return text


def _grade_expression(question: Question, student: str) -> tuple[bool, float, str]:
    left, right = _normalise_expression(student), _normalise_expression(question.correct_answer)
    if _sympy is not None:
        try:
            if _sympy.simplify(_sympy.sympify(left) - _sympy.sympify(right)) == 0:
                return True, 1.0, ""
        except Exception:
            pass  # fall through to the string comparison below
    if left == right:
        return True, 1.0, ""
    return False, 0.0, (
        f"Your expression {student!r} is not algebraically equivalent to "
        f"the correct answer {question.correct_answer!r}."
    )


def _grade_multiple_choice(question: Question, student: str) -> tuple[bool, float, str]:
    got = _strip_answer_prefix(student).strip().lower().rstrip(").")
    expected = question.correct_answer.strip().lower()
    # accept "(b)", "b)", "B" -> "b"
    got = re.sub(r"^\(?([a-z])\)?$", r"\1", got)
    if got == expected:
        return True, 1.0, ""
    return False, 0.0, (
        f"You chose option ({got or 'blank'}), but the correct option is ({expected})."
    )


def _grade_short_answer(question: Question, student: str) -> tuple[bool, float, str]:
    haystack = _norm_text(student)
    if not haystack:
        return False, 0.0, "No answer was provided for this question."
    concepts = question.key_concepts or [question.correct_answer]
    found = [c for c in concepts if _norm_text(c) in haystack]
    missing = [c for c in concepts if _norm_text(c) not in haystack]
    coverage = len(found) / len(concepts)
    if coverage >= question.pass_threshold:
        return True, 1.0, ""
    if found:
        partial = round(coverage, 2)
        return False, partial, (
            f"Your answer is on the right track but incomplete: it covers "
            f"{len(found)}/{len(concepts)} of the required ideas "
            f"({', '.join(found)}), and is missing {', '.join(missing)}."
        )
    return False, 0.0, (
        f"Your answer does not address the required ideas "
        f"({', '.join(missing)})."
    )


_GRADERS = {
    "numeric": _grade_numeric,
    "expression": _grade_expression,
    "multiple_choice": _grade_multiple_choice,
    "short_answer": _grade_short_answer,
}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def grade_question(question: Question, student_answer: Optional[str]) -> AnswerEvaluation:
    """Grade one answer. A missing/blank answer scores 0 with an explanation."""
    raw = (student_answer or "").strip()
    if not raw:
        return AnswerEvaluation(
            question_id=question.id,
            prompt=question.prompt,
            student_answer="(no answer provided)",
            correct_answer=question.correct_answer,
            is_correct=False,
            points_earned=0.0,
            points_possible=question.points,
            explanation="No answer was provided for this question.",
            correct_explanation=question.correct_explanation,
        )
    grader = _GRADERS.get(question.question_type)
    if grader is None:  # pragma: no cover - validated by Question model
        raise ValueError(f"Unsupported question type: {question.question_type!r}")
    is_correct, fraction, wrong_explanation = grader(question, raw)
    points_earned = round(question.points * fraction, 2) if not is_correct else question.points
    return AnswerEvaluation(
        question_id=question.id,
        prompt=question.prompt,
        student_answer=raw,
        correct_answer=question.correct_answer,
        is_correct=is_correct,
        points_earned=points_earned,
        points_possible=question.points,
        explanation="" if is_correct else wrong_explanation,
        correct_explanation=question.correct_explanation,
    )


def grade_submission(assignment: Assignment, answers: Dict[str, str]) -> GradedSheet:
    """Grade every question in the assignment against the student's answers."""
    evaluations = [
        grade_question(question, answers.get(question.id))
        for question in assignment.questions
    ]
    return GradedSheet(
        assignment=assignment,
        student_name="",
        student_email="",
        evaluations=evaluations,
    )
