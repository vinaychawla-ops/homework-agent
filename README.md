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
│   ├── grading.py        # Grading engine (math equivalence, science rubric)
│   ├── report.py         # Evaluated-sheet rendering (markdown + plain text)
│   └── email_service.py  # MockEmailService (records to an outbox)
├── data/samples/         # Sample submissions (txt, pdf, png)
├── tests/                # pytest suite (56 tests)
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
python demo.py image      # photo of handwritten science homework
python demo.py science    # typed-text science homework

# run the tests
python -m pytest tests/ -q
```

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

- **Image OCR:** photo submissions need `transcribed_text` in demo mode. Plug a
  vision model (e.g. Gemini vision) into `submission.parse_image()`.
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
