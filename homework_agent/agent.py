"""Google ADK agent wiring for the homework evaluator.

Pipeline (SequentialAgent):
    intake_agent    -> parse the raw submission into structured answers
    grading_agent   -> grade each answer against the answer key
    reporting_agent -> build the evaluated sheet and email student + teacher

Each stage is a deterministic FunctionTool (see pipeline.py) so the demo runs
offline; the LLM agents orchestrate and narrate. Run the offline demo with
`python demo.py` (no API key needed). For live LLM runs, set
GOOGLE_API_KEY and use `adk web` / `adk run` with this module.
"""

from __future__ import annotations

from typing import Dict, List

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import FunctionTool

from . import assignments, grading, report, submission
from .models import Assignment

MODEL = "gemini-2.0-flash"


# ---------------------------------------------------------------------------
# Tools (deterministic, offline-safe)
# ---------------------------------------------------------------------------

def intake_tool(
    assignment_id: str,
    student_name: str,
    student_email: str,
    submission_format: str,
    content: str,
    transcribed_text: str = "",
) -> Dict[str, str]:
    """Parse a homework submission (text/pdf/image) into {question_id: answer}."""
    assignment: Assignment = assignments.get_assignment(assignment_id)
    sub = submission.Submission(
        student_name=student_name,
        student_email=student_email,
        assignment_id=assignment.id,
        format=submission_format,
        content=content,
        transcribed_text=transcribed_text or None,
    )
    return submission.extract_answers(sub)


def grade_tool(assignment_id: str, answers: Dict[str, str]) -> Dict:
    """Grade extracted answers; returns per-question verdicts and totals."""
    assignment = assignments.get_assignment(assignment_id)
    sheet = grading.grade_submission(assignment, answers)
    return {
        "assignment_id": assignment.id,
        "title": assignment.title,
        "total_earned": sheet.total_earned,
        "total_possible": sheet.total_possible,
        "percentage": round(sheet.percentage, 1),
        "evaluations": [
            {
                "question_id": e.question_id,
                "is_correct": e.is_correct,
                "points_earned": e.points_earned,
                "points_possible": e.points_possible,
                "student_answer": e.student_answer,
                "correct_answer": e.correct_answer,
                "explanation": e.explanation,
                "correct_explanation": e.correct_explanation,
            }
            for e in sheet.evaluations
        ],
    }


def report_email_tool(
    assignment_id: str,
    student_name: str,
    student_email: str,
    grade_result: Dict,
) -> Dict[str, str]:
    """Build the evaluated sheet and (mock-)email it to student and teacher."""
    from .email_service import MockEmailService
    from .models import AnswerEvaluation, GradedSheet

    assignment = assignments.get_assignment(assignment_id)
    evaluations = [
        AnswerEvaluation(
            question_id=e["question_id"],
            prompt=assignment.get_question(e["question_id"]).prompt,
            student_answer=e["student_answer"],
            correct_answer=e["correct_answer"],
            is_correct=e["is_correct"],
            points_earned=e["points_earned"],
            points_possible=e["points_possible"],
            explanation=e["explanation"],
            correct_explanation=e["correct_explanation"],
        )
        for e in grade_result["evaluations"]
    ]
    sheet = GradedSheet(
        assignment=assignment,
        student_name=student_name,
        student_email=student_email,
        evaluations=evaluations,
    )
    mailer = MockEmailService()
    body = report.render_plain_text(sheet)
    student_msg = mailer.send(
        to=student_email,
        subject=report.student_subject(sheet),
        body=f"Hi {student_name},\n\nYour graded homework is below.\n\n{body}",
    )
    teacher_msg = mailer.send(
        to=assignment.teacher_email,
        subject=report.teacher_subject(sheet),
        body=f"Hi {assignment.teacher_name},\n\nGraded sheet for {student_name}:\n\n{body}",
        cc=[student_email],
    )
    return {
        "student_email_subject": student_msg.subject,
        "teacher_email_subject": teacher_msg.subject,
        "score": f"{sheet.total_earned:g}/{sheet.total_possible:g}",
    }


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

intake_agent = LlmAgent(
    name="intake_agent",
    model=MODEL,
    description="Parses raw homework submissions (typed text, PDF, or a photo of handwritten work) into structured answers.",
    instruction=(
        "You receive a homework submission. Call intake_tool with the assignment_id, "
        "student details, submission_format ('text', 'pdf', or 'image'), content "
        "(raw text, or the file path for pdf/image), and transcribed_text for images. "
        "Return the extracted answers as JSON."
    ),
    tools=[FunctionTool(intake_tool)],
)

grading_agent = LlmAgent(
    name="grading_agent",
    model=MODEL,
    description="Grades each extracted answer against the teacher's answer key.",
    instruction=(
        "You receive extracted answers for an assignment. Call grade_tool with the "
        "assignment_id and answers. Summarise which questions were correct and which "
        "were wrong, quoting the tool's explanations."
    ),
    tools=[FunctionTool(grade_tool)],
)

reporting_agent = LlmAgent(
    name="reporting_agent",
    model=MODEL,
    description="Builds the evaluated sheet and emails it to the student and teacher.",
    instruction=(
        "You receive a grade result. Call report_email_tool with the assignment_id, "
        "student name/email, and the grade result. Confirm both emails were sent and "
        "report the final score."
    ),
    tools=[FunctionTool(report_email_tool)],
)

root_agent = SequentialAgent(
    name="homework_grader",
    description="Evaluates Math/Science homework: parse submission, grade answers, email the evaluated sheet.",
    sub_agents=[intake_agent, grading_agent, reporting_agent],
)
