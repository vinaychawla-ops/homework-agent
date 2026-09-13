"""Homework Grader web demo (Hugging Face Space).

Two views behind a Student / Teacher toggle (Student is the default):

- **Student view:** pick the assignment from a dropdown, enter name and email,
  upload the homework as a photo/scan, PDF, Word (.docx), or plain text file,
  and get it graded. The teacher's email address is taken from the assignment
  itself, so the student never has to enter it.
- **Teacher view:** the full grading form (typed text, PDF/photo uploads, OCR
  mode, explicit teacher email, sample photo) plus the Create assignment tab
  for uploading answer keys.

The graded sheet is emailed to both the student and the teacher (real delivery
when Gmail credentials are configured, otherwise the UI shows which messages
would have been sent).

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

from homework_agent import answer_key, assignments, email_service, pipeline, report, submission
from homework_agent.models import Submission

ASSIGNMENT_HINT = "Available: " + ", ".join(
    f"{a.title} ({a.id})" for a in assignments.ASSIGNMENTS.values()
) + "; teacher-uploaded assignments work too — just type the title"

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
    filename: str = "",
):
    """Grade one submission and return (graded sheet markdown, email summary).

    ``teacher_email`` is optional: when blank, the assignment's own teacher
    address is used (the student view never asks for it). ``filename`` is the
    original upload name; it routes student uploads (image / PDF / Word /
    plain text) to the right parser.
    """
    if not student_name.strip():
        raise gr.Error("Please enter a student name.")
    # The teacher email is validated after the assignment is resolved below:
    # a blank field falls back to the assignment's teacher address.

    suffix = os.path.splitext(filename or "")[1].lower()
    if submission_type == "Typed text":
        if not typed_text.strip():
            raise gr.Error("Please paste the student's answers as text.")
        fmt, content = "text", typed_text
    elif submission_type == "PDF upload" or suffix == ".pdf":
        fmt, content = "pdf", _materialize_upload(upload_b64, ".pdf")
    elif suffix in (".txt", ".md", ".docx"):
        # Word / plain-text upload: read the text directly, no OCR involved.
        path = _materialize_upload(upload_b64, suffix)
        try:
            text = answer_key.extract_key_text(path, filename)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if not text.strip():
            raise gr.Error("Could not read any text from the uploaded file.")
        fmt, content = "text", text
    else:  # Photo of handwritten work (teacher view) or an image upload
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

    # The teacher's copy goes to the explicitly given address, or — when the
    # student view leaves the field blank — to the assignment's own teacher.
    teacher_email = (teacher_email or "").strip() or assignment.teacher_email
    if not teacher_email or "@" not in teacher_email:
        raise gr.Error(
            "Could not determine the teacher's email address for this "
            "assignment. Please enter it explicitly."
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
            teacher_email=teacher_email,
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
    filename: str = ""


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
            req.filename,
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


class ReadKeyRequest(BaseModel):
    filename: str = ""
    file_b64: str = ""


@api_router.post("/api/answer-key/read")
def api_read_key(req: ReadKeyRequest):
    """Transcribe an uploaded answer key and return it in the editable format.

    Accepts an image (photo/scan, handwritten or printed), PDF, .docx, or
    plain text. The teacher reviews the result in the UI before creating
    the assignment, so transcription mistakes can be fixed there.
    """
    try:
        suffix = os.path.splitext(req.filename or "")[1].lower()
        if not suffix.startswith("."):
            suffix = ".bin"
        path = _materialize_upload(req.file_b64, suffix)
        try:
            text = answer_key.extract_key_text(path, req.filename)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        headers, questions = answer_key.parse_key_text(text)
        if not questions:
            return {
                "error": "No 'Q1: <answer>' lines found in the answer key. "
                "Please check the file and try again."
            }
        return {
            "key_text": answer_key.render_key_text(headers, questions),
            "question_count": len(questions),
        }
    except gr.Error as exc:
        return {"error": str(exc)}
    except Exception as exc:  # never leak a traceback to the page
        return {"error": f"Could not read the answer key: {exc}"}


class CreateAssignmentRequest(BaseModel):
    title: str = ""
    subject: str = "math"
    teacher_name: str = ""
    teacher_email: str = ""
    key_text: str = ""


@api_router.post("/api/assignments")
def api_create_assignment(req: CreateAssignmentRequest):
    """Create a teacher-uploaded assignment from answer-key text."""
    try:
        headers, questions = answer_key.parse_key_text(req.key_text or "")
        title = req.title.strip() or headers.get("title", "").strip()
        subject = (req.subject or headers.get("subject") or "math").strip().lower()
        teacher_name = req.teacher_name.strip()
        teacher_email = req.teacher_email.strip()
        if not teacher_name and headers.get("teacher"):
            teacher_name, header_email = answer_key.parse_teacher_header(
                headers["teacher"]
            )
            teacher_email = teacher_email or header_email
        merged = {"title": title, "subject": subject}
        errors = answer_key.validate_key(merged, questions, subject=subject)
        if title and assignments.title_in_use(title):
            errors.append(f"An assignment titled {title!r} already exists.")
        if errors:
            return {"ok": False, "errors": errors}
        assignment = assignments.build_assignment(
            questions,
            title=title,
            subject=subject,
            teacher_name=teacher_name,
            teacher_email=teacher_email,
        )
        assignments.save_assignment(assignment)
        return {
            "ok": True,
            "id": assignment.id,
            "title": assignment.title,
            "question_count": len(questions),
        }
    except Exception as exc:  # never leak a traceback to the page
        return {"ok": False, "errors": [f"Could not create the assignment: {exc}"]}


@api_router.get("/api/assignments")
def api_list_assignments():
    """List built-in plus teacher-uploaded assignments."""
    known = assignments.all_assignments()
    return {
        "assignments": [
            {
                "id": a.id,
                "title": a.title,
                "subject": a.subject,
                "questions": len(a.questions),
            }
            for a in known.values()
        ]
    }


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
    // Answer-key upload (Create assignment tab): same capture pattern, its
    // own stash plus the original filename for format detection.
    window.__hg_key_b64 = '';
    window.__hg_key_name = '';
    document.addEventListener('change', (e) => {
        const t = e.target;
        if (!t || !t.matches || !t.matches('input[type="file"]')) return;
        if (!t.closest('#key-upload-box')) return;
        const f = t.files && t.files[0];
        window.__hg_key_name = (f && f.name) || '';
        if (!f) { window.__hg_key_b64 = ''; return; }
        const r = new FileReader();
        r.onload = () => {
            window.__hg_key_b64 = String(r.result).split(',')[1] || '';
        };
        r.onerror = () => { window.__hg_key_b64 = ''; };
        r.readAsDataURL(f);
    }, true);
    // Assignment list on the Create tab: refreshed after each creation too.
    const __hg_render_list = async () => {
        const el = document.getElementById('assignment-list');
        if (!el) return;
        try {
            const r = await fetch('/api/assignments');
            const data = await r.json();
            const items = (data && data.assignments) || [];
            el.innerHTML = '<b>Available assignments</b> (' + items.length + '): ' +
                items.map((a) => a.title + ' (' + a.questions + ' questions)').join(' · ');
        } catch (e) { /* leave as-is */ }
    };
    __hg_render_list();
    window.__hg_render_list = __hg_render_list;
    // Student view: capture the homework file at selection time (same reason
    // as the teacher upload hook above: Gradio may clear the file input).
    window.__hg_student_b64 = '';
    window.__hg_student_name = '';
    document.addEventListener('change', (e) => {
        const t = e.target;
        if (!t || !t.matches || !t.matches('input[type="file"]')) return;
        if (!t.closest('#student-upload-box')) return;
        const f = t.files && t.files[0];
        window.__hg_student_name = (f && f.name) || '';
        if (!f) { window.__hg_student_b64 = ''; return; }
        const r = new FileReader();
        r.onload = () => {
            window.__hg_student_b64 = String(r.result).split(',')[1] || '';
        };
        r.onerror = () => { window.__hg_student_b64 = ''; };
        r.readAsDataURL(f);
    }, true);
    // Student view: assignment dropdown, filled from the same listing (the
    // option value is the assignment id, which resolve_assignment accepts).
    const __hg_render_student_assignments = async () => {
        const sel = document.getElementById('student-assignment');
        if (!sel) return;
        try {
            const r = await fetch('/api/assignments');
            const data = await r.json();
            const items = (data && data.assignments) || [];
            sel.innerHTML = '';
            const ph = document.createElement('option');
            ph.value = '';
            ph.textContent = items.length ? 'Choose your assignment' : 'No assignments available yet';
            sel.appendChild(ph);
            items.forEach((a) => {
                const o = document.createElement('option');
                o.value = a.id;
                o.textContent = a.title + ' (' + a.questions + ' questions)';
                sel.appendChild(o);
            });
        } catch (e) { /* leave the dropdown as-is */ }
    };
    __hg_render_student_assignments();
    window.__hg_render_student_assignments = __hg_render_student_assignments;
    // Role toggle: the Student view is the default. Called by the two role
    // buttons; also run once here so the active button is styled on load.
    window.__hg_set_role = (role) => {
        const student = role !== 'teacher';
        const sv = document.getElementById('student-view');
        const tv = document.getElementById('teacher-view');
        if (sv) sv.style.display = student ? 'block' : 'none';
        if (tv) tv.style.display = student ? 'none' : 'block';
        [['role-student-btn', student], ['role-teacher-btn', !student]].forEach(([id, active]) => {
            const wrap = document.getElementById(id);
            const b = (wrap && wrap.querySelector('button')) || wrap;
            if (b) b.style.fontWeight = active ? '700' : '400';
        });
    };
    window.__hg_set_role('student');
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

_GRADE_STUDENT_JS = """async (student_name, student_email) => {
    // Student view grading: the assignment comes from the dropdown (its
    // value is the assignment id) and the teacher email is left blank so the
    // server fills it in from the assignment. Uploads may be an image, a PDF,
    // Word (.docx), or plain text — the server routes by file extension.
    const statusEl = document.getElementById('student-grade-status');
    const setStatus = (t) => { if (statusEl) statusEl.innerHTML = t; };
    setStatus('_Grading — contacting the grader…_');
    const done = (sheet, email) => { setStatus(''); return [sheet, email]; };
    const fail = (msg) => done(
        '### Could not grade this submission\\n\\n' + msg + '\\n\\n_Please retry._',
        '_No emails were sent._'
    );
    try {
        const s = (v, d) => (typeof v === 'string' && v !== null ? v : (d || ''));
        student_name = s(student_name);
        student_email = s(student_email);
        const sel = document.getElementById('student-assignment');
        const assignment_id = (sel && sel.value) || '';
        if (!assignment_id) return fail('Please choose your assignment from the list.');
        const b64 = (typeof window !== 'undefined' && window.__hg_student_b64) || '';
        const name = (typeof window !== 'undefined' && window.__hg_student_name) || '';
        if (!b64) return fail('Please upload your homework file first.');
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
                    teacher_email: '',
                    submission_type: 'Student upload',
                    typed_text: '',
                    upload_b64: b64,
                    ocr_mode: 'auto',
                    filename: name,
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

_READ_KEY_JS = """async () => {
    // Immediate feedback goes to #read-status, a dedicated element that is
    // NOT a Gradio output: writing innerHTML directly into a component that
    // is also an event output destroys its managed DOM and silently breaks
    // later output updates (the status would stay stuck forever).
    const statusEl = document.getElementById('read-status');
    const setStatus = (t) => { if (statusEl) statusEl.innerHTML = t; };
    const done = (t) => { setStatus(''); return t; };
    setStatus('_Reading the answer key…_');
    try {
        const b64 = (typeof window !== 'undefined' && window.__hg_key_b64) || '';
        const name = (typeof window !== 'undefined' && window.__hg_key_name) || '';
        if (!b64) return done('Please choose an answer-key file first.');
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 180000);
        let resp;
        try {
            resp = await fetch('/api/answer-key/read', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename: name, file_b64: b64}),
                signal: controller.signal,
            });
        } catch (e) {
            if (e && e.name === 'AbortError') return done('The request timed out after 3 minutes. Please retry.');
            throw e;
        } finally {
            clearTimeout(timeoutId);
        }
        if (!resp.ok) return done('The server returned HTTP ' + resp.status + '. Please retry.');
        const data = await resp.json();
        if (data && data.error) return done(data.error);
        // Fill the editable key box via the DOM (kept out of outputs so a
        // failed read never wipes what the teacher already typed).
        const ta = document.querySelector('#key-text-box textarea');
        if (ta && data && data.key_text) {
            ta.value = data.key_text;
            ta.dispatchEvent(new Event('input', {bubbles: true}));
        }
        const n = (data && data.question_count) || 0;
        return done('_Read ' + n + ' question(s). Review the key above — fix anything misread — then press **Create assignment**._');
    } catch (e) {
        return done(e && e.message ? e.message : String(e));
    }
}"""

_CREATE_JS = """async (title, subject, teacher_name, teacher_email, key_text) => {
    const s = (v, d) => (typeof v === 'string' && v !== null ? v : (d || ''));
    title = s(title); subject = s(subject, 'math'); teacher_name = s(teacher_name);
    teacher_email = s(teacher_email); key_text = s(key_text);
    if (!key_text.trim()) return 'Please read an answer-key file or paste the key above first.';
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);
        let resp;
        try {
            resp = await fetch('/api/assignments', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title: title, subject: subject, teacher_name: teacher_name, teacher_email: teacher_email, key_text: key_text}),
                signal: controller.signal,
            });
        } finally {
            clearTimeout(timeoutId);
        }
        if (!resp.ok) return 'The server returned HTTP ' + resp.status + '. Please retry.';
        const data = await resp.json();
        if (data && data.ok) {
            if (typeof window !== 'undefined' && window.__hg_render_list) window.__hg_render_list();
            return 'Assignment **' + data.title + '** created with ' + data.question_count + ' question(s). Students can now submit against it by name.';
        }
        const errs = (data && data.errors) || ['Unknown error.'];
        return 'Could not create the assignment:\\n\\n' + errs.map((e) => '- ' + e).join('\\n');
    } catch (e) {
        return e && e.message ? e.message : String(e);
    }
}"""


with gr.Blocks(title="Homework Grader") as demo:
    # The typed-answers box is hidden with CSS (not visible=False) so it stays
    # in the DOM: the submission-type toggle JS needs getElementById to find it.
    # (Gradio 6 moved css from Blocks() to launch(); gr.HTML <style> works with
    # mount_gradio_app on every version.)
    gr.HTML("<style>#typed-box { display: none; } #teacher-view { display: none; }</style>")
    gr.Markdown(
        """# 📝 Homework Grader
Math and Science homework, graded with explanations for every wrong answer.

**Students:** pick your assignment, enter your details, and upload your work —
a photo/scan, PDF, Word document, or text file. The graded sheet is emailed to
you and your teacher automatically.

**Teachers:** switch to the Teacher view for the full grading form and to
create new assignments from an answer key."""
    )
    with gr.Row():
        student_btn = gr.Button("🎒 Student", elem_id="role-student-btn")
        teacher_btn = gr.Button("🧑‍🏫 Teacher", elem_id="role-teacher-btn")
    # JavaScript-only role toggle (fn=None): no Gradio queue involvement.
    student_btn.click(None, js="() => window.__hg_set_role('student')")
    teacher_btn.click(None, js="() => window.__hg_set_role('teacher')")

    with gr.Column(elem_id="student-view"):
        gr.Markdown(
            "### 🎒 Submit your homework\n"
            "Choose your assignment, enter your name and email, and upload your "
            "work. Your teacher gets the graded copy automatically."
        )
        # Native <select>, filled by the page-load hook from /api/assignments
        # (a Gradio Dropdown can't be populated from JS this easily).
        gr.HTML(
            '<div style="margin-bottom: 12px;">'
            '<label for="student-assignment" style="font-weight: 600;">'
            "Assignment</label><br>"
            '<select id="student-assignment" style="width: 100%; padding: 8px; '
            'border-radius: 8px; border: 1px solid #ccc; margin-top: 4px;">'
            '<option value="">Loading assignments…</option>'
            "</select></div>"
        )
        with gr.Row():
            s_name = gr.Textbox(label="Your name", placeholder="Priya Nair")
            s_email = gr.Textbox(
                label="Your email", placeholder="priya.student@example.edu"
            )
        s_upload = gr.File(
            label="Upload your homework (photo, scanned PDF, Word, or text file)",
            file_types=["image", ".pdf", ".docx", ".txt", ".md"],
            type="filepath",
            elem_id="student-upload-box",
        )
        s_grade_btn = gr.Button("Grade my homework", variant="primary")
        s_status = gr.Markdown("", elem_id="student-grade-status")
        s_sheet = gr.Markdown(label="Graded sheet")
        s_email_out = gr.Markdown(label="Emails")
        s_grade_btn.click(
            None,
            inputs=[s_name, s_email],
            outputs=[s_sheet, s_email_out],
            js=_GRADE_STUDENT_JS,
        )
        gr.Markdown(
            "_Demo of the [homework-agent](https://github.com/vinaychawla-ops/homework-agent)"
            " project._"
        )

    # Page-load hook: captures upload bytes at selection time, fills the
    # student assignment dropdown, installs the role toggle. JavaScript-only.
    demo.load(None, js=_HOOK_JS)

    with gr.Column(elem_id="teacher-view"):
        with gr.Tab("Grade homework"):
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
                    label="Teacher email (optional — uses the assignment's teacher if blank)",
                    placeholder="ms.rivera@school.edu",
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

        with gr.Tab("Create assignment"):
            gr.Markdown(
                "### ➕ Create an assignment from an answer key\n"
                "Upload the answer key as a **photo/scan** (handwritten or printed), "
                "**PDF**, **Word (.docx)**, or **plain text** — or paste it below. "
                "The key is read and shown for review; fix anything misread, then "
                "create the assignment. Students can then submit against it by name, "
                "and it is graded against your key."
            )
            with gr.Row():
                new_title = gr.Textbox(
                    label="Assignment title", placeholder="e.g. Fractions Quiz"
                )
                new_subject = gr.Dropdown(
                    choices=["math", "science"], value="math", label="Subject"
                )
            with gr.Row():
                new_teacher_name = gr.Textbox(
                    label="Teacher name", placeholder="Jane Doe"
                )
                new_teacher_email = gr.Textbox(
                    label="Teacher email", placeholder="jane@school.edu"
                )
            key_upload = gr.File(
                label="Upload answer key (image, PDF, .docx, .txt)",
                file_types=["image", ".pdf", ".docx", ".txt", ".md"],
                type="filepath",
                elem_id="key-upload-box",
            )
            read_key_btn = gr.Button("Read answer key")
            read_status = gr.Markdown("", elem_id="read-status")
            key_text = gr.Textbox(
                label="Answer key — one question per line (review and edit)",
                placeholder="Q1 [numeric] || 3/4\nQ2 [multiple_choice] || b",
                lines=12,
                elem_id="key-text-box",
            )
            gr.Markdown(
                "Format per line: `Q1 [type] optional prompt || answer || explanation "
                "|| points: 2 || concepts: a, b`. `[type]` is one of `numeric`, "
                "`multiple_choice`, `expression`, `short_answer` — leave it out and "
                "the type is inferred from the answer (shown back in brackets for "
                "you to correct). Lines starting with `#` are ignored; `Title:`, "
                "`Subject:`, and `Teacher: Name <email>` header lines are optional."
            )
            create_btn = gr.Button("Create assignment", variant="primary")
            create_status = gr.Markdown("", elem_id="create-status")
            assignment_list = gr.Markdown("", elem_id="assignment-list")

            # JavaScript-only (fn=None): no Gradio queue, same as the Grade tab.
            read_key_btn.click(None, inputs=[], outputs=[create_status], js=_READ_KEY_JS)
            create_btn.click(
                None,
                inputs=[new_title, new_subject, new_teacher_name, new_teacher_email, key_text],
                outputs=[create_status],
                js=_CREATE_JS,
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
