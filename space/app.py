"""Homework Grader web demo (Hugging Face Space).

Upload a homework submission — typed text, a PDF, or a photo of handwritten
work — and get back the graded sheet. The assignment is optional: leave it
blank and it is auto-detected from the homework content. The graded sheet is
emailed to both the student and the teacher (real delivery when Gmail
credentials are configured, otherwise the UI shows which messages would have
been sent).

Architecture note: grading is served through a plain FastAPI endpoint
(`POST /api/grade`) that the page calls with `fetch`. Gradio's queue keeps
event state in container-local memory, and Modal can route the queue-join
POST and the follow-up event-stream GET to different containers, which made
grading fail probabilistically (404 on the event stream). A single
request/response has no cross-request server state, so it works on any
container. The Gradio UI is therefore just a form — every button is
JavaScript-only (`fn=None`).
"""

from __future__ import annotations

import base64
import os
import tempfile

import gradio as gr
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from homework_agent import assignments, email_service, pipeline, report, submission
from homework_agent.models import Submission

ASSIGNMENT_HINT = "Available: " + ", ".join(
    f"{a.title} ({a.id})" for a in assignments.ASSIGNMENTS.values()
)

OCR_CHOICES = ["auto", "docling", "vlm"]

# The sample photo is baked into the container image; every container can
# serve it, so it never depends on which container handled the page load.
SAMPLE_IMAGE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "samples", "science_homework.png"
)
for _candidate in (
    SAMPLE_IMAGE,
    "/root/data/samples/science_homework.png",
    os.path.join(os.getcwd(), "data", "samples", "science_homework.png"),
):
    if os.path.exists(_candidate):
        SAMPLE_IMAGE = _candidate
        break


def _materialize_upload(upload_b64: str, suffix: str) -> str:
    """Write the base64 upload payload to a temp file for the pipeline."""
    if upload_b64 and os.path.exists(upload_b64):
        return upload_b64  # local/dev backward compat: a real path
    try:
        raw = base64.b64decode(upload_b64 or "")
    except Exception:
        raw = b""
    if not raw:
        raise gr.Error("Please upload a file.")
    fd, dest = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return dest


def grade_homework(
    assignment_id: str,
    student_name: str,
    student_email: str,
    teacher_email: str,
    submission_type: str,
    typed_text: str,
    upload_b64: str,
    ocr_mode: str,
):
    """Grade one submission and return (graded sheet markdown, email summary)."""
    if not student_name.strip():
        raise gr.Error("Please enter a student name.")
    if not teacher_email.strip() or "@" not in teacher_email:
        raise gr.Error("Please enter the teacher's email address.")

    if submission_type == "Typed text":
        if not typed_text.strip():
            raise gr.Error("Please paste the student's answers as text.")
        fmt, content = "text", typed_text
    elif submission_type == "PDF upload":
        fmt, content = "pdf", _materialize_upload(upload_b64, ".pdf")
    else:  # Photo of handwritten work
        fmt, content = "image", _materialize_upload(upload_b64, ".png")

    # The assignment name is optional: an exact/partial name wins, otherwise
    # the assignment is auto-detected from the homework content itself.
    auto_detected = False
    transcribed_text = None
    try:
        assignment = assignments.resolve_assignment(assignment_id)
    except KeyError:
        auto_detected = True
        if fmt == "text":
            raw_text = content
        else:
            tmp = Submission(
                student_name=student_name.strip(),
                student_email=student_email.strip() or "student@example.edu",
                assignment_id="",
                format=fmt,
                content=content,
            )
            raw_text = submission._raw_text(tmp, ocr_mode=ocr_mode)
            transcribed_text = raw_text  # reuse: don't OCR a second time
        assignment = assignments.detect_assignment(raw_text)
        if assignment is None:
            available = ", ".join(
                f"{a.title} ({a.id})" for a in assignments.ASSIGNMENTS.values()
            )
            raise gr.Error(
                "Could not tell which assignment this homework belongs to. "
                f"Available: {available}. "
                "Try typing the assignment name, or include the question in the answers."
            )

    mailer = email_service.make_email_service()
    try:
        sheet, emails = pipeline.run_pipeline(
            assignment,
            student_name.strip(),
            student_email.strip() or "student@example.edu",
            fmt,
            content,
            transcribed_text=transcribed_text,
            email_service=mailer,
            ocr_mode=ocr_mode,
            teacher_email=teacher_email.strip(),
        )
    except Exception as exc:  # surface OCR / API failures readably
        # Return (don't raise): the message stays visible in the page even if
        # the session drops, instead of flashing as a toast before a reload.
        sheet_md = (
            "### Could not grade this submission\n\n"
            f"{exc}\n\n"
            "_Try a smaller or clearer photo, or switch the OCR mode and retry._"
        )
        return sheet_md, "_No emails were sent._"

    sheet_md = report.render_markdown(sheet)
    if auto_detected:
        sheet_md = (
            "_Assignment auto-detected from the homework content._\n\n" + sheet_md
        )
    email_lines = "\n".join(f"- **to:** {m.to} — {m.subject}" for m in emails)
    if isinstance(mailer, email_service.SmtpEmailService):
        email_md = (
            "### Emails sent\n\n"
            f"{email_lines}\n\n"
            f"_Sent from {mailer.sender}._"
        )
    else:
        email_md = (
            "### Emails (mock — nothing was actually sent)\n\n"
            f"{email_lines}\n\n"
            "_This demo uses a mock mailer. In production this is swapped for a real provider._"
        )
    return sheet_md, email_md


class GradeRequest(BaseModel):
    assignment_id: str
    student_name: str
    student_email: str
    teacher_email: str = ""
    submission_type: str
    typed_text: str = ""
    upload_b64: str = ""
    ocr_mode: str = "auto"


api_router = APIRouter()


@api_router.post("/api/grade")
def api_grade(req: GradeRequest):
    """Grade one submission. Single request/response — no server-side state,
    so any container can serve it."""
    try:
        sheet_md, email_md = grade_homework(
            req.assignment_id,
            req.student_name,
            req.student_email,
            req.teacher_email,
            req.submission_type,
            req.typed_text,
            req.upload_b64,
            req.ocr_mode,
        )
    except gr.Error as exc:
        sheet_md = (
            "### Could not grade this submission\n\n"
            f"{exc}\n\n"
            "_Please check your inputs and retry._"
        )
        email_md = "_No emails were sent._"
    except Exception as exc:  # never leak a traceback to the page
        sheet_md = (
            "### Could not grade this submission\n\n"
            f"{exc}\n\n"
            "_Please retry._"
        )
        email_md = "_No emails were sent._"
    return {"sheet_md": sheet_md, "email_md": email_md}


@api_router.get("/api/sample-image")
def api_sample_image():
    return FileResponse(SAMPLE_IMAGE, media_type="image/png")


_TOGGLE_JS = """(v) => {
    const showTyped = v === 'Typed text';
    document.getElementById('typed-box').style.display = showTyped ? 'block' : 'none';
    document.getElementById('upload-box').style.display = showTyped ? 'none' : 'block';
}"""

_SAMPLE_JS = """async () => {
    const r = await fetch('/api/sample-image');
    if (!r.ok) return '_Could not load the sample photo._';
    const buf = await r.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    // Stash where the Grade button looks (see page-load hook below).
    window.__hg_upload_b64 = btoa(binary);
    // The sample photo is the water-cycle homework: point the assignment
    // textbox at it so grading matches. Plain .value assignment plus a
    // synthetic input event is what Svelte (Gradio 6) listens for; the
    // native-setter dance is for React and throws "Illegal invocation"
    // when the element is a <textarea>. Wrapped in try/catch so a DOM
    // quirk can never break the photo stashing above.
    try {
        const ab = document.querySelector('#assignment-box textarea, #assignment-box input');
        if (ab) {
            ab.value = 'The Water Cycle';
            ab.dispatchEvent(new Event('input', {bubbles: true}));
        }
    } catch (e) {}
    return '_Sample photo loaded — hit **Grade homework**._';
}"""

# Runs once on page load. Captures the selected file's bytes at selection
# time into window.__hg_upload_b64. This is necessary because Gradio uploads
# the file immediately on selection and may clear or re-render the
# <input type="file"> afterwards, so reading input.files at Grade-click time
# finds nothing and grading fails with "Please upload a file." A
# document-level capture-phase listener survives component re-renders.
_HOOK_JS = """() => {
    if (window.__hgHookInstalled) return;
    window.__hgHookInstalled = true;
    window.__hg_upload_b64 = '';
    document.addEventListener('change', (e) => {
        const t = e.target;
        if (!t || !t.matches || !t.matches('input[type="file"]')) return;
        if (!t.closest('#upload-box')) return;
        const f = t.files && t.files[0];
        if (!f) { window.__hg_upload_b64 = ''; return; }
        const r = new FileReader();
        r.onload = () => {
            window.__hg_upload_b64 = String(r.result).split(',')[1] || '';
        };
        r.onerror = () => { window.__hg_upload_b64 = ''; };
        r.readAsDataURL(f);
    }, true);
}"""

_GRADE_JS = """async (assignment_id, student_name, student_email, teacher_email, submission_type, typed_text, ocr_mode) => {
    // Immediate feedback: this runs before any await, so if the event fires
    // at all the user sees it. If even this never appears, the click handler
    // itself is not running (not a network issue).
    const statusEl = document.getElementById('grade-status');
    const setStatus = (t) => { if (statusEl) statusEl.innerHTML = t; };
    setStatus('_Grading — contacting the grader…_');
    const done = (sheet, email) => { setStatus(''); return [sheet, email]; };
    const fail = (msg) => done(
        '### Could not grade this submission\\n\\n' + msg + '\\n\\n_Please retry._',
        '_No emails were sent._'
    );
    try {
        // Defensive coercion: Gradio may pass undefined/null for untouched or
        // hidden inputs, and JSON.stringify drops undefined keys — either one
        // trips the API's required-field validation (HTTP 422). Coerce here so
        // the request always validates and the backend's graceful "please
        // check your inputs" handling takes over instead of a cryptic 422.
        const s = (v, d) => (typeof v === 'string' && v !== null ? v : (d || ''));
        assignment_id = s(assignment_id, 'Rainbows');
        student_name = s(student_name);
        student_email = s(student_email);
        teacher_email = s(teacher_email);
        submission_type = s(submission_type, 'Photo of handwritten work');
        typed_text = s(typed_text);
        ocr_mode = s(ocr_mode, 'auto');
        // Read the file bytes captured at selection time by the page-load
        // hook (window.__hg_upload_b64). The bytes travel with this request,
        // so grading never depends on which container served what — and never
        // on the file input still holding the selection at click time.
        let b64 = (typeof window !== 'undefined' && window.__hg_upload_b64) || '';
        if (!b64 && (submission_type === 'Photo of handwritten work' || submission_type === 'PDF upload')) {
            return fail('No file was captured. Please re-select the file and try again.');
        }
        // AbortController timeout: a hung connection must surface as an error,
        // never as eternal silence.
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 180000);
        let resp;
        try {
            resp = await fetch('/api/grade', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    assignment_id: assignment_id,
                    student_name: student_name,
                    student_email: student_email,
                    teacher_email: teacher_email,
                    submission_type: submission_type,
                    typed_text: typed_text,
                    upload_b64: b64,
                    ocr_mode: ocr_mode,
                }),
                signal: controller.signal,
            });
        } catch (e) {
            if (e && e.name === 'AbortError') {
                return fail('The request timed out after 3 minutes. The server may be busy — please retry.');
            }
            throw e;
        } finally {
            clearTimeout(timeoutId);
        }
        if (!resp.ok) {
            return fail('The server returned HTTP ' + resp.status + '. Please retry.');
        }
        const data = await resp.json();
        if (!data || typeof data.sheet_md !== 'string') {
            return fail('The server returned an unexpected response. Please retry.');
        }
        return done(data.sheet_md, data.email_md || '_No emails were sent._');
    } catch (e) {
        return fail(e && e.message ? e.message : String(e));
    }
}"""


with gr.Blocks(title="Homework Grader") as demo:
    # The typed-answers box is hidden with CSS (not visible=False) so it stays
    # in the DOM: the submission-type toggle JS needs getElementById to find it.
    # (Gradio 6 moved css from Blocks() to launch(); gr.HTML <style> works with
    # mount_gradio_app on every version.)
    gr.HTML("<style>#typed-box { display: none; }</style>")
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
        assignment = gr.Textbox(
            label="Assignment (name or ID) — optional, auto-detected if blank or unknown",
            value="",
            placeholder="e.g. Rainbows — leave blank and the app figures it out",
            elem_id="assignment-box",
        )
        ocr_mode = gr.Radio(
            choices=OCR_CHOICES, value="auto", label="OCR mode (images only)"
        )
    gr.Markdown("_" + ASSIGNMENT_HINT + "_")
    with gr.Row():
        student_name = gr.Textbox(label="Student name", placeholder="Priya Nair")
        student_email = gr.Textbox(
            label="Student email", placeholder="priya.student@example.edu"
        )
        teacher_email = gr.Textbox(
            label="Teacher email", placeholder="ms.rivera@school.edu"
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
        elem_id="typed-box",
    )
    upload = gr.File(
        label="Upload file",
        file_types=["image", ".pdf"],
        type="filepath",
        elem_id="upload-box",
    )
    # Hidden: base64 bytes staged by the sample-photo button. A user-selected
    # file is read by the Grade button's JavaScript instead.
    sample_status = gr.Markdown("")

    # All events below are JavaScript-only (fn=None): no Gradio queue, so no
    # per-container event state for Modal's load balancer to split up.
    # Page-load hook: captures upload bytes at selection time (see _HOOK_JS).
    demo.load(None, js=_HOOK_JS)
    submission_type.change(None, inputs=submission_type, js=_TOGGLE_JS)

    with gr.Row():
        grade_btn = gr.Button("Grade homework", variant="primary")
        sample_btn = gr.Button("Use sample photo")
    grade_status = gr.Markdown("", elem_id="grade-status")

    sample_btn.click(None, inputs=[], outputs=[sample_status], js=_SAMPLE_JS)

    sheet_out = gr.Markdown(label="Graded sheet")
    email_out = gr.Markdown(label="Emails")

    grade_btn.click(
        None,
        inputs=[
            assignment,
            student_name,
            student_email,
            teacher_email,
            submission_type,
            typed_text,
            ocr_mode,
        ],
        outputs=[sheet_out, email_out],
        js=_GRADE_JS,
    )

    gr.Markdown(
        "_Demo of the [homework-agent](https://github.com/vinaychawla-ops/homework-agent)"
        " project. Email delivery is live when Gmail credentials are configured,"
        " otherwise mocked._"
    )

# The Modal deployment wires the same router in modal_app.py (registered on
# the parent FastAPI app before Gradio is mounted).
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Compose exactly like the Modal deployment: API routes first, then the
    # Gradio UI mounted at /. (demo.launch() rebuilds demo.app internally,
    # so the router has to live on the parent app, not demo.app.)
    _app = FastAPI()
    _app.include_router(api_router)
    gr.mount_gradio_app(_app, demo, path="/")
    uvicorn.run(_app, host="0.0.0.0", port=7860)
