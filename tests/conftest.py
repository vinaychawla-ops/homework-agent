"""Shared fixtures for the homework-agent test suite."""

import os

import pytest

from homework_agent import assignments
from homework_agent.models import Assignment, Question

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "samples")


@pytest.fixture()
def math_assignment() -> Assignment:
    return assignments.get_assignment("math-fractions-01")


@pytest.fixture()
def science_assignment() -> Assignment:
    return assignments.get_assignment("sci-water-cycle-01")


@pytest.fixture()
def math_question(math_assignment) -> Question:
    return math_assignment.get_question("Q1")


def sample_path(name: str) -> str:
    return os.path.join(SAMPLES, name)
