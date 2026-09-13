# AGENTS.md — Homework Evaluator Agent

Notes for AI agents working on this repo. Keep this file current when behavior changes.

## Architecture

- **Deterministic core** (`pipeline.py`, `grading.py`, `submission.py`, `ocr.py`,
  `report.py`, `email_service.py`) does all real work. Tests target this;
  `ocr.py` is the only part that can touch the network (Docling VLM path).
- **OCR** (`ocr.py`): Docling standard pipeline for printed/scanned docs;
  Docling VLM pipeline via OpenRouter (`google/gemma-4-31b-it:free`) for
  handwriting. Key comes from `OPENROUTER_API_KEY` env only; `OCR_IMAGE_MODE`
  (`auto`|`docling`|`vlm`) overrides the path. Supplied `transcribed_text`
  still skips OCR (deterministic demos/tests).
- **ADK layer** (`agent.py`) is thin orchestration: `root_agent` (SequentialAgent)
  of `intake_agent` → `grading_agent` → `reporting_agent`, each exposing one
  `FunctionTool` that calls the deterministic core. Do not put grading logic in
  agent prompts; prompts only orchestrate and narrate.
- **Demo** (`demo.py`) calls `pipeline.run_pipeline` directly — no API key, same
  logic the agents use.
- **Browser UI** (`space/app.py`): Gradio `Blocks` UI with two tabs. The
  *Grade homework* tab calls `pipeline.run_pipeline` for typed/PDF/image
  submissions and renders the graded Markdown sheet; the *Create assignment*
  tab lets a teacher upload an answer key (image, PDF, .docx, .txt) or paste
  one, reviews the parsed key, and saves it via
  `assignments.save_assignment` (persisted under `HOMEWORK_ASSIGNMENTS_DIR`;
  on Modal this is the `homework-assignments` volume). Email is real delivery when Gmail credentials are
  configured (see below), otherwise the mock mailer (recipients listed,
  nothing sent). Deployed on Modal via `modal_app.py` (image with Docling +
  baked OCR models, served with `gr.mount_gradio_app` on FastAPI through
  `@modal.asgi_app()`). Grading is a plain FastAPI `POST /api/grade`
  (no Gradio queue: the queue keeps event state in container-local memory and
  Modal's load balancer can split the queue-join POST and the event-stream
  GET across containers, 404ing the stream). The page calls the endpoint with
  `fetch`, sending the file's base64 bytes with the single request — no
  cross-container filesystem dependency and no cross-request server state.
  Keep UI logic thin — grading stays in the core.

## Conventions

- Question ids are uppercase `Q<n>`; parsing is case-insensitive.
- `grading.grade_question` never raises on student input — garbage/missing answers
  score 0 with an explanation. It may raise only on programmer errors (bad key).
- New question types: add to `models.VALID_QUESTION_TYPES`, add a grader in
  `grading._GRADERS`, add tests in `tests/test_grading.py`.
- New subjects: extend `models.VALID_SUBJECTS` (currently `math`, `science` only —
  this is a product constraint, keep it).
- Teacher-uploaded assignments: `answer_key.py` parses/uploads keys
  (`extract_key_text` per file type, `parse_key_text` for the `Q1 || answer`
  format, `infer_question_type` when `[type]` is omitted);
  `assignments.build_assignment` + `save_assignment` persist them as JSON under
  `HOMEWORK_ASSIGNMENTS_DIR`, and `all_assignments()` (used by
  `get/resolve/detect_assignment`) merges them with the built-ins. Never put
  grading logic in the UI — the Create tab only parses, previews, and saves.
- Email: `SmtpEmailService` sends real email via Gmail SMTP (needs
  `GMAIL_SENDER` + `GMAIL_APP_PASSWORD` env); `make_email_service()` picks it
  when both are set, otherwise falls back to `MockEmailService` so local
  dev/tests never send. `MockEmailService.outbox` is the assertion point in
  tests; `sent_to()` filters by recipient. `run_pipeline(teacher_email=...)`
  overrides the assignment's teacher address — the web UI collects the
  teacher's email on the form and every grading goes to both student and
  teacher. On Modal, the Gmail credentials live in the `gmail-smtp` secret
  (optional; skipped when absent).

## Running things

- Venv: `~/workspace/venvs/homework-agent` (has google-adk, pytest, pypdf, sympy,
  docling, gradio, modal).
- Tests: `python -m pytest tests/ -q` from repo root. Keep the suite green; 142 tests
  at last count (Docling OCR paths are stubbed in tests - no network).- Demo: `python demo.py [math|pdf|image|science|all]`.
- Gradio UI: `python space/app.py` (needs `gradio>=5.0`).
- Modal deploy: `modal deploy modal_app.py` from repo root with
  `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` set (from modal.com/settings/tokens).
  The OpenRouter key must exist as a Modal secret named `openrouter-api-key`
  (env `OPENROUTER_API_KEY`) or the handwriting VLM path errors gracefully.
  Verify with `modal run modal_verify.py`. Redeploys reuse the cached image
  (seconds) unless the image definition changes.

## Known demo seams (production TODOs)

1. `email_service.SmtpEmailService` — live when the `gmail-smtp` Modal secret
   exists; pending until the dedicated sender Gmail account is accessible.
2. Short-answer grading is keyword-concept matching; an LLM judge would give
   richer feedback.
3. Free-tier OpenRouter rate limits can make the VLM handwriting path flaky;
   retries with backoff are built in, but a paid key or self-hosted VLM would
   be steadier for production.
4. Modal deployment: the app scales to zero when idle, so the first request
   after inactivity pays a cold start (~15s: container boot + torch import).
   OCR models are baked into the image at build time (`warmup_docling`), so
   they are not re-downloaded per container.

## Sample data

- `data/samples/math_homework.pdf` is generated by an inline script (minimal
  hand-built PDF); if it ever fails to parse, regenerate it rather than
  hand-editing the binary.
- `data/samples/science_homework.png` is a pillow-rendered stand-in for a photo
  of handwritten work.
