"""Tests for the assignment registry: the Rainbows assignment and free-text
assignment resolution (the web UI uses a textbox, not a dropdown)."""

import pytest

from homework_agent import assignments
from homework_agent.assignments import detect_assignment, get_assignment, resolve_assignment


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


def test_detect_assignment_rainbow_photo_text():
    text = (
        "Q17 How is rainbow created in the sky Ans. When you have rain and "
        "shine at the same time; rain drops reflect sunlight into the sky"
    )
    assert detect_assignment(text).id == "sci-rainbows-01"


def test_detect_assignment_water_cycle_text():
    text = (
        "Q1: b Q2: puddles disappear because heat evaporates the water into "
        "water vapor Q3: condensation Q4: a"
    )
    assert detect_assignment(text).id == "sci-water-cycle-01"


def test_detect_assignment_fractions_text():
    text = "Q1: 3/4 Q2: x=4 Q3: b Q4: x^2+5x+6 Q5: 5/8 of the pizza is left"
    assert detect_assignment(text).id == "math-fractions-01"


def test_detect_assignment_answer_only_no_question_restated():
    # No question prompt in the text; key concepts still identify it.
    text = "A rainbow forms when sunlight shines through rain drops."
    assert detect_assignment(text).id == "sci-rainbows-01"


def test_detect_assignment_gibberish_returns_none():
    assert detect_assignment("asdf qwer zxcv hello world foo bar") is None


def test_detect_assignment_empty_returns_none():
    assert detect_assignment("") is None
    assert detect_assignment("   ") is None


def test_detect_assignment_ambiguous_returns_none():
    # Only generic words shared across assignments -> no clear winner.
    assert detect_assignment("explain in one or two sentences what happens") is None
