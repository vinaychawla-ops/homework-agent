"""Renders a GradedSheet into the evaluated sheet sent back to student & teacher."""

from __future__ import annotations

from .models import AnswerEvaluation, GradedSheet


def render_markdown(sheet: GradedSheet) -> str:
    lines = [
        f"# Graded Homework: {sheet.assignment.title}",
        "",
        f"**Student:** {sheet.student_name} ({sheet.student_email})",
        f"**Teacher:** {sheet.assignment.teacher_name}",
        f"**Score:** {sheet.total_earned:g} / {sheet.total_possible:g} "
        f"({sheet.percentage:.1f}%) - "
        f"{sheet.correct_count}/{len(sheet.evaluations)} correct",
        "",
        "---",
    ]
    for ev in sheet.evaluations:
        mark = "Correct" if ev.is_correct else "Incorrect"
        lines += [
            "",
            f"## {ev.question_id} - {mark} "
            f"({ev.points_earned:g}/{ev.points_possible:g} pts)",
            "",
            f"**Question:** {ev.prompt}",
            "",
            f"**Student answer:** {ev.student_answer}",
            "",
        ]
        if ev.is_correct:
            lines.append(f"Well done. {ev.correct_explanation}")
        else:
            lines += [
                f"**Why it's wrong:** {ev.explanation}",
                "",
                f"**Correct answer:** {ev.correct_answer}",
                "",
                f"**Explanation:** {ev.correct_explanation}",
            ]
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_plain_text(sheet: GradedSheet) -> str:
    lines = [
        f"Graded Homework: {sheet.assignment.title}",
        f"Student: {sheet.student_name} <{sheet.student_email}>",
        f"Teacher: {sheet.assignment.teacher_name}",
        f"Score: {sheet.total_earned:g} / {sheet.total_possible:g} "
        f"({sheet.percentage:.1f}%) - {sheet.correct_count}/{len(sheet.evaluations)} correct",
        "=" * 60,
    ]
    for ev in sheet.evaluations:
        mark = "CORRECT" if ev.is_correct else "INCORRECT"
        lines += [
            "",
            f"{ev.question_id} [{mark}] ({ev.points_earned:g}/{ev.points_possible:g} pts)",
            f"  Question: {ev.prompt}",
            f"  Student answer: {ev.student_answer}",
        ]
        if ev.is_correct:
            lines.append(f"  Note: {ev.correct_explanation}")
        else:
            lines += [
                f"  Why it's wrong: {ev.explanation}",
                f"  Correct answer: {ev.correct_answer}",
                f"  Explanation: {ev.correct_explanation}",
            ]
    return "\n".join(lines).strip() + "\n"


def student_subject(sheet: GradedSheet) -> str:
    return (
        f"Your graded homework: {sheet.assignment.title} - "
        f"{sheet.total_earned:g}/{sheet.total_possible:g} ({sheet.percentage:.0f}%)"
    )


def teacher_subject(sheet: GradedSheet) -> str:
    return (
        f"Graded homework from {sheet.student_name}: {sheet.assignment.title} - "
        f"{sheet.total_earned:g}/{sheet.total_possible:g} ({sheet.percentage:.0f}%)"
    )
