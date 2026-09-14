"""End-to-end grading pipeline: parse -> grade -> report -> email.

This is the deterministic core the ADK agents call through their tools, and
what the offline demo (`demo.py`) runs directly without any LLM API key.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from . import assignments, grading, report, submission
from .email_service import EmailMessage, MockEmailService
from .models import Assignment, GradedSheet, Submission


def run_pipeline(
    assignment: Assignment,
    student_name: str,
    student_email: str,
    submission_format: str,
    content: str,
    transcribed_text: str | None = None,
    email_service: MockEmailService | None = None,
    ocr_mode: str | None = None,
    teacher_email: str | None = None,
) -> tuple[GradedSheet, List[EmailMessage]]:
    """Grade one homework submission and email the evaluated sheet.

    Returns (graded_sheet, [student_email, teacher_email]).

    ``ocr_mode`` controls Docling transcription for image submissions without
    ``transcribed_text``: "auto" (default), "docling", or "vlm". It can also
    be set with the OCR_IMAGE_MODE environment variable.

    ``teacher_email`` overrides the assignment's teacher address (the web UI
    collects it from the teacher on the form).
    """
    mailer = email_service or MockEmailService()
    teacher_email = (teacher_email or "").strip() or assignment.teacher_email

    sub = Submission(
        student_name=student_name,
        student_email=student_email,
        assignment_id=assignment.id,
        format=submission_format,
        content=content,
        transcribed_text=transcribed_text,
    )
    answers: Dict[str, str] = submission.extract_answers(
        sub,
        ocr_mode=ocr_mode,
        # Single-question assignments (e.g. a photographed page whose "Q1:"
        # label the OCR mangled) grade the whole text as that one answer
        # rather than scoring a certain zero.
        fallback_question_id=(
            assignment.questions[0].id if len(assignment.questions) == 1 else None
        ),
        # Answers that merely repeat the question text (common in photo
        # transcriptions) are discarded and grade as "no answer provided".
        question_prompts={q.id: q.prompt for q in assignment.questions},
    )
    sheet = grading.grade_submission(assignment, answers)
    sheet = replace(sheet, student_name=student_name, student_email=student_email)

    body_text = report.render_plain_text(sheet)
    body_md = report.render_markdown(sheet)
    full_body = body_text + "\n\n--- Markdown version ---\n\n" + body_md
    attachment = f"{assignment.id}-{student_name.replace(' ', '_')}-graded.md"

    student_msg = mailer.send(
        to=student_email,
        subject=report.student_subject(sheet),
        body=(
            f"Hi {student_name},\n\n"
            f"Your homework '{assignment.title}' has been graded. "
            f"Your score: {sheet.total_earned:g}/{sheet.total_possible:g} "
            f"({sheet.percentage:.1f}%).\n\n"
            f"See the full evaluated sheet below.\n\n" + full_body
        ),
        attachments=[attachment],
    )
    teacher_msg = mailer.send(
        to=teacher_email,
        subject=report.teacher_subject(sheet),
        body=(
            f"Hi {assignment.teacher_name},\n\n"
            f"{student_name} <{student_email}> submitted '{assignment.title}'. "
            f"Score: {sheet.total_earned:g}/{sheet.total_possible:g} "
            f"({sheet.percentage:.1f}%), {sheet.correct_count}/{len(sheet.evaluations)} correct.\n\n"
            f"Evaluated sheet:\n\n" + full_body
        ),
        cc=[student_email],
        attachments=[attachment],
    )
    return sheet, [student_msg, teacher_msg]
