# Homework Evaluator Agent

A Google ADK (Python) agent that grades Math and Science homework and emails the
evaluated sheet back to the student and the teacher.

**How it works**

1. A student submits homework as **typed text**, a **PDF upload**, or a **photo/scan**
   of handwritten work.
2. The agent parses the submission into per-question answers.
3. Each answer is graded against the teacher's answer key:
   - **Correct** → marked correct.
   - **Wrong** → marked wrong, with an explanation of *why the student's answer is
     incorrect* plus an *explanation of the correct answer*.
4. The evaluated sheet is emailed to **both the student and the teacher**
   (mock email service in this demo; swap in a real provider later).

**Subjects:** Math and Science only. Open-ended short answers are supported via a
key-concept rubric with partial credit.

## Project layout

```
homework-agent/
├── homework_agent/
│   ├── agent.py          # Google ADK wiring: root_agent (SequentialAgent)
│   │                     #   intake_agent -> grading_agent -> reporting_agent
│   ├── pipeline.py       # Deterministic core: parse -> grade -> report -> email
│   ├── models.py         # Question, Assignment, Submission, GradedSheet, ...
│   ├── assignments.py    # Sample Math + Science assignments with answer keys
│   ├── submission.py     # Parsers for text / PDF / image submissions
│   ├── ocr.py            # Docling OCR (standard) + OpenRouter VLM handwriting
│   ├── grading.py        # Grading engine (math equivalence, science rubric)
│   ├── report.py         # Evaluated-sheet rendering (markdown + plain text)
│   └── email_service.py  # MockEmailService (records to an outbox)
├── space/
│   ├── app.py                # Gradio browser UI (upload/type homework, get graded sheet)
│   ├── Dockerfile            # Container build for the Gradio UI
│   └── requirements-space.txt
├── modal_app.py          # Modal deployment: builds the image, serves the Gradio UI
├── modal_verify.py       # One-off check that the OpenRouter secret + VLM path work on Modal
├── data/samples/         # Sample submissions (txt, pdf, png)
├── tests/                # pytest suite (86 tests)
├── demo.py               # Offline end-to-end demo (no API key needed)
├── requirements.txt
├── README.md
└── AGENTS.md
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# run the offline demo (no API key needed)
python demo.py            # all samples
python demo.py math       # typed-text math homework (all correct)
python demo.py pdf        # PDF math homework (all wrong -> explanations)
python demo.py image      # photo of handwritten science homework (supplied transcription)
python demo.py science    # typed-text science homework
python demo.py ocr        # real Docling OCR on the sample photo (see below)

# run the tests
python -m pytest tests/ -q
```

## Browser demo (Gradio UI)

`space/app.py` is a Gradio web UI on top of the same deterministic pipeline:
enter the student, optionally name the assignment (or leave it blank — the
app auto-detects which assignment the homework belongs to from its content),
then submit typed text, a PDF, or a homework photo, and get the graded sheet
back in the browser. Email stays
mock-only (recipients are shown, nothing is sent).

```bash
pip install "gradio>=5.0"
python space/app.py   # then open http://127.0.0.1:7860
```

The UI is also deployed publicly on Modal (free-tier credits):

**https://chawlavinay--homework-grader-web.modal.run**

To redeploy (`modal_app.py` builds the container image with Docling baked in
and serves the Gradio app as an ASGI app):

```bash
pip install modal
export MODAL_TOKEN_ID=ak-... MODAL_TOKEN_SECRET=as-...   # from modal.com/settings/tokens
modal deploy modal_app.py
```

Handwriting VLM mode on the deployment needs a Modal secret named
`openrouter-api-key` containing `OPENROUTER_API_KEY` (dashboard → Secrets);
without it, image grading falls back to the local Docling pipeline.
`modal run modal_verify.py` checks the secret and the VLM path end-to-end.

Note: Hugging Face Spaces was evaluated for hosting but Docker/Gradio Spaces
there now require a paid subscription, so Modal is the current host.

## Handwriting OCR (Docling)

Photo/scan submissions are transcribed with [Docling](https://github.com/docling-project/docling)
(`homework_agent/ocr.py`) instead of a supplied transcription:

| Path | When | Needs |
|---|---|---|
| Standard pipeline | Printed or scanned documents, and photos when no key is set | `pip install -r requirements.txt` (runs locally; the first run downloads OCR model assets, then works offline) |
| VLM pipeline | Handwritten homework photos | `OPENROUTER_API_KEY` — routes through OpenRouter to Google's free `google/gemma-4-31b-it:free` model |

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."   # from https://openrouter.ai/keys
python demo.py ocr                          # photo -> OCR -> grade -> mock email
```

Optional overrides: `OPENROUTER_MODEL` (default `google/gemma-4-31b-it:free`),
`OCR_IMAGE_MODE` (`auto` | `docling` | `vlm`, default `auto`). Scanned PDFs
with no usable text layer automatically fall back to Docling OCR.

Notes:

- The API key lives only in your environment — it is never written to the repo,
  logs, or committed files.
- The free OpenRouter tier is rate-limited and shared, so handwriting
  transcription may occasionally return a "rate limit" error; the pipeline
  retries a few times with backoff, then reports the failure instead of
  grading garbage.
- Passing `transcribed_text` explicitly (as `demo.py image` does) still skips
  OCR entirely — useful for deterministic demos and tests.

## Using the ADK agents live

`homework_agent/agent.py` defines `root_agent`, a `SequentialAgent` with three
`LlmAgent` stages (`intake_agent` → `grading_agent` → `reporting_agent`), each
backed by a deterministic `FunctionTool`. With a `GOOGLE_API_KEY` set you can run:

```bash
adk web    # then select the homework_grader agent
# or
adk run homework_agent
```

The deterministic core (`pipeline.run_pipeline`) is what the tools call, so the
offline demo exercises the exact same grading logic as the live agent.

## Answer format

Text and PDF submissions list one answer per line:

```
Q1: 3/4
Q2: x = 4
Q3: b
```

Question ids are case-insensitive. Unanswered questions are marked wrong (0 pts).

## Grading rules

| Type | Rule |
|---|---|
| `numeric` | Fraction/decimal/percentage equivalence within `tolerance` (e.g. `3/4` == `0.75`) |
| `expression` | Symbolic equivalence via sympy, else normalized comparison (`x^2+5x+6` == `6 + 5*x + x**2`) |
| `multiple_choice` | Case-insensitive letter match (`B`, `(b)` → `b`) |
| `short_answer` | Key-concept coverage ≥ `pass_threshold` (default 0.7) counts as correct; otherwise proportional partial credit, and the explanation names the missing concepts |

## Demo limitations (to wire up for production)

- **Email:** `MockEmailService` records to an in-memory outbox (+ optional JSONL
  log). Replace with Gmail API / SMTP for real delivery.
- **Grading:** the engine is deterministic and offline. For richer feedback on
  open-ended answers, route `short_answer` grading through an LLM judge.

## Adding your own assignment

```python
from homework_agent.models import Assignment, Question
from homework_agent import assignments

a = Assignment(
    id="math-quiz-02", title="Quiz 2", subject="math",
    teacher_name="Ms. Rivera", teacher_email="rivera.teacher@example.edu",
    questions=[Question(id="Q1", subject="math", prompt="...",
                        question_type="numeric", correct_answer="42",
                        correct_explanation="...")],
)
assignments.ASSIGNMENTS[a.id] = a
```

Then grade with `pipeline.run_pipeline(a, student_name, student_email, "text", "Q1: 42")`.
