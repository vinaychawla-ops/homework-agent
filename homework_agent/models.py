"""Core data models for the homework evaluator agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


VALID_SUBJECTS = ("math", "science")
VALID_QUESTION_TYPES = ("numeric", "expression", "multiple_choice", "short_answer")
VALID_FORMATS = ("text", "pdf", "image")


@dataclass
class Question:
    """A single homework question with its answer key."""

    id: str                      # e.g. "Q1"
    subject: str                 # "math" | "science"
    prompt: str                  # the question text shown to the student
    question_type: str           # "numeric" | "expression" | "multiple_choice" | "short_answer"
    correct_answer: str          # canonical correct answer
    correct_explanation: str     # explanation of the correct answer (always shown on a miss)
    key_concepts: List[str] = field(default_factory=list)  # required concepts for short_answer
    points: float = 1.0
    tolerance: float = 1e-6      # numeric comparison tolerance
    pass_threshold: float = 0.7  # short_answer: fraction of concepts needed to count as correct

    def __post_init__(self) -> None:
        if self.subject not in VALID_SUBJECTS:
            raise ValueError(f"Unsupported subject {self.subject!r}; expected one of {VALID_SUBJECTS}")
        if self.question_type not in VALID_QUESTION_TYPES:
            raise ValueError(f"Unsupported question type {self.question_type!r}; expected one of {VALID_QUESTION_TYPES}")


@dataclass
class Assignment:
    """A homework assignment created by a teacher."""

    id: str
    title: str
    subject: str
    teacher_name: str
    teacher_email: str
    questions: List[Question]

    def __post_init__(self) -> None:
        if self.subject not in VALID_SUBJECTS:
            raise ValueError(f"Unsupported subject {self.subject!r}; expected one of {VALID_SUBJECTS}")

    def get_question(self, question_id: str) -> Question:
        for q in self.questions:
            if q.id == question_id:
                return q
        raise KeyError(f"Question {question_id!r} not found in assignment {self.id!r}")

    @property
    def max_points(self) -> float:
        return sum(q.points for q in self.questions)


@dataclass
class Submission:
    """A student's homework submission before answer extraction."""

    student_name: str
    student_email: str
    assignment_id: str
    format: str                                  # "text" | "pdf" | "image"
    content: str                                 # raw text, or filesystem path for pdf/image
    transcribed_text: Optional[str] = None       # demo-mode transcription for image submissions

    def __post_init__(self) -> None:
        if self.format not in VALID_FORMATS:
            raise ValueError(f"Unsupported submission format {self.format!r}; expected one of {VALID_FORMATS}")
        if self.format == "image" and not self.transcribed_text:
            # Real deployments plug a vision/OCR model in here; the demo requires
            # the transcription to be supplied so grading stays deterministic.
            raise ValueError(
                "Image submissions require 'transcribed_text' in demo mode. "
                "Wire an OCR/vision model into submission.extract_answers() for production."
            )


@dataclass
class AnswerEvaluation:
    """The grading result for one question."""

    question_id: str
    prompt: str
    student_answer: str
    correct_answer: str
    is_correct: bool
    points_earned: float
    points_possible: float
    explanation: str            # why the student's answer is wrong ("" when correct)
    correct_explanation: str    # explanation of the correct answer


@dataclass
class GradedSheet:
    """The full evaluated homework sheet for one student."""

    assignment: Assignment
    student_name: str
    student_email: str
    evaluations: List[AnswerEvaluation]

    @property
    def total_earned(self) -> float:
        return sum(e.points_earned for e in self.evaluations)

    @property
    def total_possible(self) -> float:
        return sum(e.points_possible for e in self.evaluations)

    @property
    def percentage(self) -> float:
        if self.total_possible == 0:
            return 0.0
        return 100.0 * self.total_earned / self.total_possible

    @property
    def correct_count(self) -> int:
        return sum(1 for e in self.evaluations if e.is_correct)
