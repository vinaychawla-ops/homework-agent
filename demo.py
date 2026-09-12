"""Offline demo: grade sample homework submissions end-to-end (no API key needed).

Usage:
    python demo.py            # grades all sample submissions (deterministic; skips the ocr job)
    python demo.py math       # only the math text sample
    python demo.py pdf        # only the PDF sample
    python demo.py image      # only the image sample (supplied transcription)
    python demo.py science    # only the science sample
    python demo.py ocr        # real Docling OCR on the sample photo instead of
                              # the supplied transcription (needs OPENROUTER_API_KEY
                              # for the handwriting VLM path; without it the
                              # standard local OCR pipeline is used)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from homework_agent import assignments, email_service, pipeline, report

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "samples")


def show(sheet, emails):
    print(report.render_plain_text(sheet))
    print("\n--- emails sent (mock) ---")
    for m in emails:
        print(f"  to={m.to} subject={m.subject!r} attachments={m.attachments}")
    print("=" * 70 + "\n")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    math = assignments.get_assignment("math-fractions-01")
    science = assignments.get_assignment("sci-water-cycle-01")
    mailer = email_service.MockEmailService()

    def read(name: str) -> str:
        with open(os.path.join(BASE, name), encoding="utf-8") as f:
            return f.read()

    jobs = {
        "math": lambda: pipeline.run_pipeline(
            math, "Alex Kumar", "alex.student@example.edu", "text",
            read("math_homework_alex.txt"), email_service=mailer),
        "pdf": lambda: pipeline.run_pipeline(
            math, "Ben Carter", "ben.student@example.edu", "pdf",
            os.path.join(BASE, "math_homework.pdf"), email_service=mailer),
        "image": lambda: pipeline.run_pipeline(
            science, "Priya Nair", "priya.student@example.edu", "image",
            os.path.join(BASE, "science_homework.png"),
            transcribed_text=read("science_homework_priya.txt"),
            email_service=mailer),
        "science": lambda: pipeline.run_pipeline(
            science, "Priya Nair", "priya.student@example.edu", "text",
            read("science_homework_priya.txt"), email_service=mailer),
        "ocr": lambda: pipeline.run_pipeline(
            science, "Priya Nair", "priya.student@example.edu", "image",
            os.path.join(BASE, "science_homework.png"),
            email_service=mailer),
    }
    if which == "ocr":
        from homework_agent import ocr as _ocr

        if not _ocr.docling_available():
            print("Docling is not installed. Run: pip install -r requirements.txt")
            sys.exit(1)
        if not os.environ.get(_ocr.ENV_API_KEY):
            print(
                f"Note: {_ocr.ENV_API_KEY} is not set, so the standard local OCR "
                "pipeline is used. Set it to transcribe handwriting with the "
                "Gemma VLM via OpenRouter."
            )
    selected = (
        [k for k in jobs.keys() if k != "ocr"] if which == "all" else [which]
    )
    for key in selected:
        print(f"\n########## demo: {key} ##########")
        sheet, emails = jobs[key]()
        show(sheet, emails)
    print(f"Total mock emails in outbox: {len(mailer.outbox)}")


if __name__ == "__main__":
    main()
