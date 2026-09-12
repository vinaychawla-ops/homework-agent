"""Homework Grader web demo (Hugging Face Space).

Upload a homework submission — typed text, a PDF, or a photo of handwritten
work — pick an assignment, and get back the graded sheet. Email delivery is
mocked: the UI shows which messages would have been sent.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import gradio as gr

from homework_agent import assignments, pipeline, report
from homework_agent.email_service import MockEmailService

ASSIGNMENT_CHOICES = [
    ("Math: Fractions (math-fractions-01)", "math-fractions-01"),
    ("Science: The Water Cycle (sci-water-cycle-01)", "sci-water-cycle-01"),
]

OCR_CHOICES = ["auto", "docling", "vlm"]

SAMPLE_IMAGE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "samples", "science_homework.png"
)


def _save_upload(upload_path: str, suffix: str) -> str:
    fd, dest = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    shutil.copyfile(upload_path, dest)
    return dest


def grade_homework(
    assignment_id: str,
    student_name: str,
    student_email: str,
    submission_type: str,
    typed_text: str,
    upload: str | None,
    ocr_mode: str,
):
    """Grade one submission and return (graded sheet markdown, email summary)."""
    if not student_name.strip():
        raise gr.Error("Please enter a student name.")
    try:
        assignment = assignments.get_assignment(assignment_id)
    except KeyError:
        raise gr.Error(f"Unknown assignment {assignment_id!r}.")

    if submission_type == "Typed text":
        if not typed_text.strip():
            raise gr.Error("Please paste the student's answers as text.")
        fmt, content = "text", typed_text
    elif submission_type == "PDF upload":
        if not upload:
            raise gr.Error("Please upload a PDF file.")
        fmt, content = "pdf", _save_upload(upload, ".pdf")
    else:  # Photo of handwritten work
        if not upload:
            raise gr.Error("Please upload a photo of the homework.")
        fmt, content = "image", _save_upload(upload, ".png")

    mailer = MockEmailService()
    try:
        sheet, emails = pipeline.run_pipeline(
            assignment,
            student_name.strip(),
            student_email.strip() or "student@example.edu",
            fmt,
            content,
            email_service=mailer,
            ocr_mode=ocr_mode,
        )
    except Exception as exc:  # surface OCR / API failures readably
        raise gr.Error(f"Could not grade this submission: {exc}")

    sheet_md = report.render_markdown(sheet)
    email_lines = "\n".join(f"- **to:** {m.to} — {m.subject}" for m in emails)
    email_md = (
        "### Emails (mock — nothing was actually sent)\n\n"
        f"{email_lines}\n\n"
        "_This demo uses a mock mailer. In production this is swapped for a real provider._"
    )
    return sheet_md, email_md


with gr.Blocks(title="Homework Grader") as demo:
    gr.Markdown(
        """# 📝 Homework Grader
Upload a homework submission and get it graded — Math and Science, with
explanations for every wrong answer.

**How it works:** printed/scanned pages are read with Docling's local OCR.
For handwriting, pick the **vlm** mode to transcribe with Google Gemma via
OpenRouter (needs an `OPENROUTER_API_KEY` secret on the deployment) —
otherwise the local pipeline does its best."""
    )
    with gr.Row():
        assignment = gr.Dropdown(
            choices=ASSIGNMENT_CHOICES,
            value="sci-water-cycle-01",
            label="Assignment",
        )
        ocr_mode = gr.Radio(
            choices=OCR_CHOICES, value="auto", label="OCR mode (images only)"
        )
    with gr.Row():
        student_name = gr.Textbox(label="Student name", placeholder="Priya Nair")
        student_email = gr.Textbox(
            label="Student email", placeholder="priya.student@example.edu"
        )
    submission_type = gr.Radio(
        choices=["Typed text", "PDF upload", "Photo of handwritten work"],
        value="Photo of handwritten work",
        label="Submission type",
    )
    typed_text = gr.Textbox(
        label="Typed answers",
        placeholder="Q1: b\nQ2: ...",
        lines=6,
        visible=False,
    )
    upload = gr.File(
        label="Upload file",
        file_types=["image", ".pdf"],
        type="filepath",
    )

    def _toggle(submission_type: str):
        return (
            gr.update(visible=submission_type == "Typed text"),
            gr.update(visible=submission_type != "Typed text"),
        )

    submission_type.change(
        _toggle, inputs=submission_type, outputs=[typed_text, upload]
    )

    grade_btn = gr.Button("Grade homework", variant="primary")
    sheet_out = gr.Markdown(label="Graded sheet")
    email_out = gr.Markdown(label="Emails")

    grade_btn.click(
        grade_homework,
        inputs=[
            assignment,
            student_name,
            student_email,
            submission_type,
            typed_text,
            upload,
            ocr_mode,
        ],
        outputs=[sheet_out, email_out],
    )

    if os.path.exists(SAMPLE_IMAGE):
        gr.Examples(
            examples=[[SAMPLE_IMAGE]],
            inputs=upload,
            label="Try the sample homework photo",
        )

    gr.Markdown(
        "_Demo of the [homework-agent](https://github.com/vinaychawla-ops/homework-agent)"
        " project. Email delivery is mocked._"
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
