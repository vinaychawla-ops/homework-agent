"""Tests for the assignment registry: the Rainbows assignment and free-text
assignment resolution (the web UI uses a textbox, not a dropdown)."""

import pytest

from homework_agent import assignments
from homework_agent.assignments import get_assignment, resolve_assignment


def test_rainbow_assignment_registered():
    a = get_assignment("sci-rainbows-01")
    assert a.title == "Rainbows"
    assert a.subject == "science"
    assert len(a.questions) == 1
    assert a.questions[0].id == "Q1"
    assert a.questions[0].question_type == "short_answer"


def test_resolve_assignment_exact_id():
    assert resolve_assignment("sci-rainbows-01").id == "sci-rainbows-01"
    assert resolve_assignment("math-fractions-01").id == "math-fractions-01"


def test_resolve_assignment_title_case_insensitive():
    assert resolve_assignment("rainbows").id == "sci-rainbows-01"
    assert resolve_assignment("Rainbows").id == "sci-rainbows-01"
    assert resolve_assignment("THE WATER CYCLE").id == "sci-water-cycle-01"


def test_resolve_assignment_unambiguous_substring():
    assert resolve_assignment("water").id == "sci-water-cycle-01"
    assert resolve_assignment("fraction").id == "math-fractions-01"
    assert resolve_assignment("rainbow").id == "sci-rainbows-01"


def test_resolve_assignment_unknown_lists_available():
    with pytest.raises(KeyError) as excinfo:
        resolve_assignment("Astrophysics")
    assert "Rainbows" in str(excinfo.value)


def test_resolve_assignment_blank():
    with pytest.raises(KeyError):
        resolve_assignment("   ")


def test_all_assignments_resolve_by_title():
    for a in assignments.ASSIGNMENTS.values():
        assert resolve_assignment(a.title).id == a.id
