# E2E Failure Log — Homework Grader (Modal)

Started: 2026-09-12 ~17:20 EDT. Updated as investigation proceeds.

## The failure
Clicking **"Grade homework"** in the browser UI at
https://chawlavinay--homework-grader-web.modal.run produces **zero output**:
no graded sheet, no "Could not grade" error, no loading indicator.
Reproduced 4x (2x sample-photo flow, 1x real upload flow, 1x repeat after
page reload), each waited ~5 min. The "Use sample photo" button works
(status message appears), so JS events in general fire — only the Grade
button's handler is dead.

## Verified WORKING (not the problem)
- `POST /api/grade` (curl): typed text → graded sheet in 1–2s ✅
- `POST /api/grade` (curl): Vin's JPEG photo via docling → graded sheet in 22s ✅
- `POST /api/grade` (curl): full-res 3024×4032 photo via auto → graded sheet in 29s, no HTTP 413 ✅
- `POST /api/grade` (curl): PDF upload via auto → graded sheet in 13s ✅
- `GET /api/sample-image` (curl): valid PNG ✅
- Missing file + photo selected → graceful "Could not grade" message ✅
- Grading correctness: sample PDF with wrong answers scores 0/6 correctly;
  Vin's rainbow photo vs water-cycle key scores 0/5 correctly (content mismatch,
  not a bug). OCR transcription of handwriting works ✅
- `pytest`: 92 passed ✅
- All three JS snippets pass `node --check` ✅
- Deployed `/config` contains the `/api/grade` JS ✅

## Ruled out
- Backend `/api/grade` — works via curl, healthy right now.
- JS syntax errors — all snippets valid.
- Gradio js-event machinery — inspected the installed Gradio 5.x frontend
  bundle: `fn=None` + `js=` correctly routes the js return value to outputs
  (and the sample-photo button proves it works on this page).

## Open hypotheses (under investigation)
1. The browser's `fetch('/api/grade')` never resolves/rejects (hangs) —
   but then the `catch` would never fire either, matching the silence.
2. `document.querySelector('#upload-box input[type="file"]')` or the
   FileReader path throws *before* the try/catch (it's outside it).
3. Modal proxy intermittently truncates responses (`/config` showed
   `IncompleteRead` on 1 of 3 fetches) — could break the page's fetch.
4. A Gradio frontend quirk with 7 inputs on a js-only event.

## Next steps
- Playwright + headless Chromium installing: will drive the LOCAL app
  (http://localhost:7860, already running) with console/network capture to
  see the actual JS error or failed request.
- Depending on findings: fix `_GRADE_JS` (e.g. move file-read inside
  try/catch, add loading status + timeout), redeploy to Modal, re-run full
  browser E2E, update GitHub.

## Fixes applied

### 2026-09-12 ~18:10 EDT — bulletproofed `_GRADE_JS` (space/app.py)
Root cause still not definitively identified (browser automation unavailable
in sandbox; Modal logs need Vin's token). The new js eliminates ALL silent
failure modes:
- Immediate "Grading — contacting the grader…" status via direct DOM update
  (`#grade-status`) BEFORE any await. If the click handler fires at all, the
  user sees this. If even this never appears, the event wiring itself is
  broken (diagnostic).
- `AbortController` + 180s timeout: a hung connection now surfaces as
  "request timed out" instead of eternal silence.
- `resp.ok` check: HTTP errors (500/502/413) now display instead of hitting
  `resp.json()` on an error page.
- Response shape validation: unexpected JSON displays an error.
- FileReader wrapped in its own try/catch (was outside the main try).
- Status cleared on success/failure.
- Verified in Node with Gradio's exact `I(e)`/`Y(...)` frontend parsing:
  loading status shows mid-flight, success clears it, HTTP 500 / bad JSON /
  network failure all produce visible error sheets.
- `pytest`: 92 passed. Local server restarted with new js; `/config`
  confirms 3234-char js with AbortController + grade-status + resp.ok.

### Still needed
- Vin's Modal token to redeploy (he's at dinner; ask when back).
- After redeploy: full browser E2E via managed browser task.
- Then: push to GitHub (needs reconciliation with remote main first).

## 2026-09-12 ~17:35 EDT update
- Inspected deployed `/config`: grade event is registered correctly (7 inputs,
  2 outputs, `backend_fn=False`, correct 1508-char js). Config itself is fine.
- NEW FINDING: Modal's `/config` endpoint is FLAKY — repeated
  `IncompleteRead` truncations (3/3 failed, then 1/3 failed on retry).
  Local app's `/config` is 3/3 solid. So Modal's proxy is truncating
  responses intermittently. Unclear yet if this affects `/api/grade` POSTs
  from the browser (a truncated JSON response would hit the js `catch` and
  display "Could not grade" — but nothing displays at all, so this alone
  doesn't explain the silence).
- Playwright + Chromium installing for a local headed debug with console +
  network capture (browser-task VMs can't reach localhost).

## 2026-09-12 ~17:45 EDT update — frontend js machinery analyzed
- Extracted Gradio 5.x's exact js-event handling from the installed frontend
  bundle: `I(e)` wraps user js via `new Function('return (\n'+js+'\n);')`,
  then `Y(...)` awaits it and maps the return to outputs.
- Replicated `I(e)` in Node with our actual `_GRADE_JS`: parses fine,
  executes fine, returns `[sheet_md, email_md]` with mocked fetch.
  → The js LOGIC is not the bug; the failure is in the live browser
  environment (event never fires, or fetch/FileReader never settles).
- `run()` in the frontend: for our event (no backend fn) it does
  `i = await this.functions.frontend(t)` then `{type:'data', data:i}`.
  If the js promise never settles, nothing ever renders — matches the
  observed silence exactly.
