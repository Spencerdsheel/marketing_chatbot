# Widget dev host page — manual test harness

This is the **real acceptance test** for Sprint S14.1, Sprint S14.2, Sprint S14.3, Sprint S14.4, Sprint
S14.5, Sprint S14.6, and Sprint SR-3 (per `dev_plan/sprints/S14.1.md` / `dev_plan/sprints/S14.2.md` /
`dev_plan/sprints/S14.3.md` / `dev_plan/sprints/S14.4.md` / `dev_plan/sprints/S14.5.md` /
`dev_plan/sprints/S14.6.md` / `dev_plan/sprints/SR-3-widget-conversation-continuity-across-reload.md` /
Phase 14's stated test method): a local HTML host page embedding the
widget, loaded against a real, locally-running backend. Not Postman, not the admin-web browser
walkthrough.

**S14.1** proved admission (`POST /widget/session`) + Shadow-DOM isolation with a non-interactive
placeholder badge. **S14.2** replaces that badge with a real chat launcher + panel wired to
`POST /public/chat/message` — run S14.1's 7 steps first (they are still valid regression checks, now
folded into S14.2 step 7 below), then S14.2's walkthrough. **S14.3** replaces the `action="lead_form"`
stub line with a real consent-gated lead form wired to `POST /public/leads` — run S14.1's + S14.2's steps
first (S14.2 step 7 already folds in S14.1's regressions; S14.3 step 6 below folds in both), then S14.3's
walkthrough. **S14.4** replaces the `action="schedule_cta"` stub line with a real consent-gated booking
flow wired to `GET /public/schedule/slots` + `POST /public/schedule/book` — run S14.1's + S14.2's +
S14.3's steps first (S14.3 step 6 already folds in S14.1/S14.2; S14.4 step 7 below folds in all three),
then S14.4's walkthrough. **S14.5** adds no new endpoint calls — it hardens the a11y of every surface
above (panel focus trap/restore/Escape, live-region announcements, keyboard operability, AA contrast/
reduced-motion) and adds an opt-in browser TTS greeting — run S14.1–S14.4's steps first (S14.4 step 7
already folds in all of them), then S14.5's walkthrough below. **This is the sprint that most needs a
real screen reader (VoiceOver/NVDA/Narrator) and a contrast-checker, not just the backend** — the unit
suite can only prove structural guarantees (roles/attributes/focus targets), never real spoken output or
measured contrast. **S14.6**, the final sprint of Phase 14, adds no new endpoint calls either — it wraps
admission + turn sends in a bounded retry/backoff layer, adds an honest connection-status indicator +
manual Retry control, and a bounded (never unbounded) session re-mint on a `401`/`403` — run
S14.1–S14.5's steps first (S14.5 step 6 already folds in all of them), then S14.6's walkthrough below.
**This is the sprint that most needs the backend process itself stopped/started on purpose and the
admission rate limit hammered on purpose** — the unit suite proves the bounded-attempt-count and
backoff-scheduling invariants precisely (with an injected clock), but only a live pass can show a real
`Network` tab with real timing gaps and a real `429`. **SR-3**, an out-of-band review-remediation sprint
(not part of Phase 14 proper), adds an **opt-in, tenant-gated** conversation-continuity mechanism: reload
the page (or navigate same-tab to another page carrying the widget) and, when the tenant has
`widget_session_resume` enabled, the SAME conversation continues instead of fragmenting into a new one —
run S14.1–S14.6's steps first (S14.6 step 7 already folds in all of them), then SR-3's walkthrough below.
**This is the sprint that most needs `sessionStorage` inspected by hand** — the unit suite proves the TTL/
PII-minimization/isolation invariants precisely, but only a live pass can show the actual stored JSON, a
real reload skipping the mint fetch, and a real cross-visitor-rejection round trip in the Network tab.

## Precondition: seed a dev origin into a tenant's `allowed_origins`

`origin_allowed()` in `services/api/src/api/gateway/sessions.py` is an **exact string match** — no
wildcard, no scheme/port normalization. The Vite dev server serves this page from
`http://localhost:5173`, so a tenant's `allowed_origins` array must contain **exactly**
`http://localhost:5173` (no trailing slash) before `POST /widget/session` will succeed.

This is a one-line manual step, not something this sprint automates (S14.1 makes no backend/seed
changes — see the spec's Constraints). Do ONE of:

- If a seeded tenant already has a usable `allowed_origins` entry, note its `pk_...` client key and skip
  ahead.
- Otherwise, add `http://localhost:5173` to a tenant's `allowed_origins` yourself (via the admin console,
  a direct SQL update in your local dev DB, or however you normally edit tenant config in this repo) and
  note that tenant's `pk_...` client key.

You will need that key for step 3 below.

## Additional precondition for S14.2: an LLM-configured, knowledge-ingested tenant

S14.1's walkthrough only needed a tenant with a valid `allowed_origins` entry. **S14.2's happy-path step
(step 2 below) additionally needs that tenant configured with a working LLM provider and at least some
ingested knowledge**, so `POST /public/chat/message` actually answers instead of failing fast with
`LLM_NOT_CONFIGURED` / `RAG_EMBEDDING_NOT_CONFIGURED`. If you don't have such a tenant handy, you can still
run the walkthrough — an immediate config-error turn is itself a valid, honest-failure exercise of step 5
(turn failure UX), just not of the step-2 happy path.

## Running the harness

1. **Start the backend** (from the repo root, in your normal way — e.g. `uvicorn` against your local
   Postgres/Redis). Confirm it's reachable at `http://localhost:8000` (or update `data-api-base` in
   `host.html` to match).
2. **Install deps + start the widget dev server:**
   ```
   cd apps/widget
   npm install
   npm run dev
   ```
   This serves `dev/host.html` (and the unbundled `src/entry.tsx` via Vite's dev module graph) at
   `http://localhost:5173`.
3. **Set the client key.** Open `apps/widget/dev/host.html` and replace
   `REPLACE_WITH_REAL_CLIENT_KEY` in the `<script>` tag's `data-client-key` attribute with the real
   `pk_...` key from the precondition step above.
4. **Open the host page:** navigate to `http://localhost:5173/dev/host.html` in a browser.

## S14.1 walkthrough steps (spec Tests section — run all 7)

1. **Happy path.** Reload the page. The minimal "Chat" placeholder badge appears bottom-right. DevTools
   console shows `[chatbot-widget] visitor session minted, expires_at=...`. DevTools Network tab shows
   exactly one `POST /widget/session` request → `200` with `{ visitor_token, expires_at }`, request
   `Origin: http://localhost:5173`, **no `tenant_id`** anywhere in the request body, and no cookie
   sent/set.
2. **Isolation proof.** Inspect the page: the widget's DOM lives under a `#shadow-root (open)` node under
   the auto-created `#chatbot-widget-root` div. Confirm the host page's serif styling does not affect the
   placeholder badge, and the placeholder's styling does not leak onto the host page's button. Check
   `document.cookie`, `localStorage`, and `sessionStorage` in the console — none contain the visitor
   token.
3. **Wrong key.** Change `data-client-key` to a bogus value (e.g. `pk_bogus`), reload. Console shows an
   `INVALID_CLIENT_KEY` admission-failure log with a `correlation_id`. No placeholder renders. The rest of
   the host page is untouched.
4. **Disallowed Origin.** Either load the page from a different origin (e.g. via a different hostname/port
   not on the tenant's allowlist) or point `data-client-key` at a tenant whose `allowed_origins` does NOT
   include `http://localhost:5173`. Console shows `ORIGIN_NOT_ALLOWED`, handled honestly — no UI, page
   intact.
5. **Missing key.** Remove the `data-client-key` attribute entirely, reload. Console shows
   `MISSING_CLIENT_KEY`. Nothing mounts at all (no shadow host created). Page intact.
6. **Debug strip.** With `data-debug="true"` (the default in this `host.html`), repeat step 3 (wrong key).
   The diagnostic strip — `error_code` / `message` / `correlation_id` — renders inside the shadow root,
   above the (absent) placeholder position. Confirm it's still invisible for the step-1 success case
   (only errors render the strip).
7. **Backend down.** Stop the backend process, reload. Console shows a `NETWORK_ERROR` admission failure
   (fetch rejection), handled honestly — no UI, and critically **no retry storm**: exactly one failed
   `POST /widget/session` attempt in the Network tab, not a loop.

## S14.2 walkthrough steps (spec Tests section — run all 7)

Run these against the same running backend + host page as above (S14.1's own 7 steps still apply as
regressions — see step 7 below). The launcher now opens a real chat panel instead of doing nothing.

1. **Open the panel.** `npm run dev` (if not already running) + open `dev/host.html`. The launcher
   ("Chat") appears bottom-right, same as S14.1. **Click it → the chat panel opens** inside the shadow
   root (inspect: the panel's DOM lives under `#shadow-root (open)`, isolated from the host page's serif
   styling both directions — same isolation proof as S14.1 step 2, now for real chat UI). Click again to
   close it (button label toggles "Chat" / "Close").
2. **Happy turn.** Type a question into the input and send it (press Enter, or click the Send button). A
   **user bubble** appears immediately (optimistic render), a **typing/thinking indicator** shows next,
   then a **bot bubble** renders the reply. In DevTools Network tab: exactly one
   `POST /public/chat/message` → `200`, carrying `Authorization: Bearer <visitor token>`, **no
   `tenant_id` anywhere in the request body**, and a JSON response with
   `conversation_id`/`reply`/`decision`/`action`. (If the tenant has no LLM/RAG config, this turn instead
   surfaces the honest error line from step 5 below — see the "Additional precondition" note above.)
3. **Continuity.** Send a second, follow-up message in the same panel. In the Network tab, confirm the
   second request body's `conversation_id` matches the value the **first** response returned — the
   conversation continues as one thread, not two.
4. **Markdown safety.** Ask something whose reply is likely to contain formatting (bold/italic/inline
   code/a URL) — confirm it renders styled (bold text, a clickable link with `rel="noopener noreferrer"`,
   etc.), not as literal asterisks/backticks. This is the visual confirmation only — `Markdown.test.tsx`
   is the hard XSS gate (a reply containing `<img onerror=...>` / `<script>` text renders as inert visible
   text with no corresponding DOM element, proven in the unit suite, not exercisable live without a
   compromised/malicious backend).
5. **Honest turn failure.** Point the widget at a tenant with no LLM provider configured (or otherwise
   make a turn fail — e.g. temporarily stop a backend dependency the LLM call needs) and send a message.
   Confirm: a **non-bubble error line** appears in the message list (visibly not a bot reply, e.g. "Sorry —
   something went wrong. Please try again."), the console logs the `error_code` + `correlation_id`, the
   input **re-enables** so you can retry manually, and — critically — there is **no retry storm**: exactly
   one `POST /public/chat/message` request in the Network tab per send, not a loop.
6. **`action` stub.** Drive a turn that returns `action="lead_form"` or `action="schedule_cta"` (typically
   an `escalate`/`blocked` decision — e.g. ask something clearly outside the tenant's knowledge, or
   whatever your seeded tenant's guardrail/escalation config triggers). Confirm the bot's reply renders
   **plus** an honest, clearly-labelled stub line below it ("(A lead form will appear here)" /
   "(Scheduling options will appear here)") — and confirm **no** actual lead form or booking UI appears
   (those ship in S14.3/S14.4).
7. **Regression — S14.1 invariants still hold.** Re-run S14.1's wrong-key / disallowed-origin /
   missing-key / backend-down-at-boot scenarios (steps 3/4/5/7 above): they must still fail exactly as
   before (console + no UI / debug strip; page intact). Check `document.cookie`, `localStorage`, and
   `sessionStorage` — the visitor token is still in memory only, and the new `conversation_id` is
   likewise never written to any of them (reload the page mid-conversation and confirm the chat panel
   comes back empty with a fresh session, not a resumed thread).

## S14.3 walkthrough steps (spec Tests section — run all 6)

Run these against the same running backend + host page as above (S14.1's + S14.2's steps still apply as
regressions — see step 6 below). Additional precondition beyond S14.2's: your seeded tenant/knowledge
config needs to be able to produce an `action="lead_form"` turn — the same escalate/blocked path S14.2
step 6 used (e.g. ask something the bot escalates on / has no knowledge for).

1. **Drive a `lead_form` turn.** Open the panel, send a message that returns `action="lead_form"`
   (whatever your tenant's guardrail/escalation config triggers — see S14.2 step 6). The bot reply renders
   **plus the real lead form** (name/email/phone + consent checkbox) inline below it — **not** the old
   `"(A lead form will appear here)"` stub line.
2. **Consent gate.** Confirm the consent checkbox is **unchecked** on appearance and the **Submit button
   is disabled**. Fill name + email but leave consent unchecked → Submit stays disabled. Check consent →
   Submit enables. Confirm in the Network tab that **no** `POST /public/leads` request has been made yet —
   the first request must be triggered by clicking Submit, not by filling fields or checking the box.
3. **Happy submit.** With name+email filled (phone optional) and consent checked, click Submit. The
   Network tab shows exactly one `POST /public/leads` → `201`, carrying `Authorization: Bearer …`, **no
   `tenant_id` anywhere in the request body**, and a `consent: { granted:true, purpose, text }` object
   whose `text` matches the checkbox label exactly. The form is replaced by an honest confirmation message
   (e.g. "Thanks — we've got your details…"); there is no form/Submit button left to resubmit from.
4. **Honest failure.** Force a failure — e.g. stop the backend (or a dependency it needs), or wait out the
   30-minute visitor token TTL then submit — and confirm: an **honest error line** appears near the form
   (visibly not a success/confirmation), the console logs `error_code` + `correlation_id` (open DevTools
   first), the form **re-enables** (fields + Submit usable again) for manual retry, and there is **no
   retry storm** — exactly one `POST /public/leads` attempt in the Network tab per Submit click. Confirm
   **no** "thanks" confirmation is ever shown for a failed submit.
5. **PII / storage hygiene.** After a submit (success or failure), check `document.cookie`, `localStorage`,
   and `sessionStorage` in the console — **none** contain the name/email/phone or the visitor token; the
   console logs on failure carry only `error_code`/`correlation_id`/status, never the submitted PII.
6. **Regression — S14.1/S14.2 invariants hold.** Re-run S14.2's step 7 regressions (S14.1's wrong-key /
   disallowed-origin / missing-key / backend-down-at-boot scenarios) — they still fail exactly as before.
   The chat loop, `conversation_id` continuity, markdown safety, and admission/isolation all behave exactly
   as S14.2; the visitor token + `conversation_id` remain in memory only. (As of S14.4, a turn returning
   `action="schedule_cta"` renders the real booking flow rather than a stub — see the S14.4 walkthrough
   section below.)

## S14.4 walkthrough steps (spec Tests section — run all 7)

Run these against the same running backend + host page as above (S14.1's + S14.2's + S14.3's steps still
apply as regressions — see step 7 below). Additional preconditions beyond S14.3's:

- Your seeded tenant/knowledge config needs to be able to produce an `action="schedule_cta"` turn — the
  same escalate/blocked path S14.2 step 6 / S14.3 step 1 used.
- **For the happy path (steps 2 and 4 below), that tenant additionally needs availability configured** so
  `GET /public/schedule/slots` returns open slots. An unconfigured tenant (or one with no availability in
  the query window) correctly exercises the honest empty-state instead — that's a valid, honest run of step
  2's "no availability" branch, just not the happy path.

1. **Drive a `schedule_cta` turn.** Open the panel, send a message that returns `action="schedule_cta"`
   (whatever your tenant's guardrail/escalation config triggers). The bot reply renders **plus the real
   scheduling CTA** inline below it — **not** the old `"(Scheduling options will appear here)"` stub line.
   The Network tab shows one `GET /public/schedule/slots` → `200`, carrying `Authorization: Bearer …`, and
   **no `tenant_id` anywhere** in the request.
2. **Honest availability.** With availability configured, the CTA shows selectable open slots **in your
   local timezone** — compare a slot's displayed time to its raw UTC `starts_at` in the Network response's
   `200` body (they should differ by your UTC offset: same instant, localized display). With an
   unconfigured tenant (or an empty window), it shows an honest **"No times are currently available"**
   message — never a made-up slot.
3. **Consent gate.** Select a slot → the confirm step appears showing the chosen time, an **unchecked**
   consent checkbox, and a **disabled Confirm** button. Confirm in the Network tab that **no**
   `POST /public/schedule/book` request has been made yet. Check consent → Confirm enables.
4. **Happy booking.** Click Confirm. The Network tab shows exactly one `POST /public/schedule/book` →
   `201`, carrying `Authorization: Bearer …`, **no `tenant_id` anywhere** in the request body, a
   `starts_at` that **exactly matches** the selected slot's UTC string from step 1/2's `/slots` response,
   and a truthful `consent: { granted:true, purpose, text }` object. An honest **confirmation** renders
   naming the booked local time; the slot picker is gone — there's no way to rebook that slot from this
   panel instance.
5. **No double-book / honest `SLOT_UNAVAILABLE`.** In a second browser/session (or by racing two booking
   attempts for the same slot), attempt to book a slot that's already taken. The widget shows an honest
   error (**not** a confirmation), automatically **re-fetches** the slot list (a second
   `GET /public/schedule/slots` in the Network tab) so the taken slot is gone, and lets you pick another.
   Confirm the backend never created two events for the same slot (e.g. check the scheduling table / admin
   console).
6. **Honest booking failure.** Force a `CALENDAR_SYNC_FAILED` (a tenant with a calendar configured to fail
   sync) or another booking failure (e.g. an expired 30-minute visitor token mid-flow). Confirm: an honest
   error line renders (visibly not a confirmation), the console logs `error_code` + `correlation_id`, **no**
   confirmation is shown for the rolled-back booking, there is **no retry storm** (exactly one
   `POST /public/schedule/book` per Confirm click, and — for a non-`SLOT_UNAVAILABLE` failure specifically —
   **no** automatic re-fetch either), and the host page stays intact.
7. **Storage / cross-tenant hygiene + regression.** After the flow, check `document.cookie`,
   `localStorage`, and `sessionStorage` in the console — **none** contain the visitor token, the booking, or
   the slot list. The `lead_form` branch (S14.3) still renders the real lead form unaffected; the chat loop,
   `conversation_id` continuity, markdown safety, and admission/isolation all behave exactly as S14.1–S14.3
   (re-run S14.3's step 6 regressions). The visitor token/`conversation_id` remain in memory only.

## S14.5 walkthrough steps (spec Tests section — run all 6)

Run these against the same running backend + host page as above (S14.1's–S14.4's steps still apply as
regressions — see step 6 below). No new preconditions beyond S14.4's. Additional tools needed: a screen
reader (VoiceOver on macOS, NVDA or Narrator on Windows) and a contrast checker (browser DevTools'
built-in contrast ratio in the color picker, or a checker extension).

1. **Keyboard-only chat.** With the mouse untouched: `Tab` to the launcher, `Enter`/`Space` to open —
   focus lands **inside** the panel (on the message input). `Tab` cycles **within** the panel and never
   escapes to the host page (tabbing past the last focusable control wraps to the first; `Shift+Tab` at
   the first wraps to the last). Type + `Enter` sends. `Escape` closes the panel and focus **returns to
   the launcher button**. Every focused control — launcher, input, send button, mute toggle — shows a
   **visible focus outline**.
2. **Screen-reader announcements.** With the screen reader on: sending a message and receiving a reply,
   the **bot reply is announced** (politely, once, without interrupting anything in progress); if you
   force a turn failure, the **error line is announced assertively** (interrupts); the **typing
   indicator is not spammed** (it stays silent throughout). In the lead form: the **success confirmation
   and any error are announced**, and focus lands on the confirmation when it appears. In the schedule
   CTA: the **loading state, the empty-state, and the booking confirmation/error are announced**
   (`role="status"`/`role="alert"`), and each **slot's time is read** when focused (tab through the slot
   list and confirm the announced name is the localized time, not a raw index or empty string).
3. **Keyboard-only lead form + schedule CTA.** Drive an `action="lead_form"` turn and complete the whole
   form — including checking the **consent checkbox** — mouse-free (Tab between fields, Space to toggle
   the checkbox, Enter/click-equivalent on Submit). Drive an `action="schedule_cta"` turn and complete a
   booking (Tab to a slot button, Enter to select it, Tab to the consent checkbox, Space to check it, Tab
   to Confirm, Enter to confirm) mouse-free. Both flows are fully operable and visibly focused throughout,
   and focus moves sensibly across each step transition (slot list → confirm step → confirmation).
4. **Reduced motion + contrast.** Enable `prefers-reduced-motion` (OS setting: macOS Accessibility >
   Display > Reduce Motion; Windows Settings > Accessibility > Visual Effects > Animation Effects off) →
   reload and trigger the typing indicator (send a message) → the dots no longer bounce (static, still
   visible). Turn the OS setting back off → the dots bounce again. Run a contrast checker over the panel
   header, message bubbles (both user and bot), the (now-removed-from-live-use but still-styled)
   action-stub text if you can trigger it, lead-form labels/inputs/error/confirmation, schedule-CTA slot
   buttons/labels/consent/error/confirmation, and the mute toggle → all body text meets **AA (≥4.5:1)**,
   and UI components / focus indicators meet **≥3:1**.
5. **TTS opt-in + gesture + mute + degradation.** Reload the page fresh (clears the page-session "already
   greeted" flag). **Before opening the panel**, confirm nothing speaks — no audio, and no
   `speechSynthesis` activity in a "Web Speech API" trace if your browser's DevTools expose one. **Click
   the launcher to open the panel** (the user gesture) — the greeting should speak if your OS/browser has
   a TTS voice available and permissions allow it. Close and reopen the panel — the greeting does **not**
   speak again (it only ever fires once per page session, on the *first* open). Reload the page, open the
   panel, then immediately click the **Mute** toggle in the header — confirm any in-progress speech stops
   and `aria-pressed` on the toggle reflects the muted state; close and reopen — still no speech; click
   **Unmute** — the toggle reflects the unmuted state (note: per this sprint's design, unmuting does not
   retroactively re-trigger the already-consumed first-open greeting — that's expected, not a bug). In a
   browser without Web Speech support (or with it blocked by an extension/policy), confirm the Mute
   toggle still renders and is clickable as a harmless no-op, and — critically — **chat is completely
   unaffected**: no error thrown into the host page, no console error, sending/receiving messages still
   works normally.
6. **Regression — S14.1–S14.4 invariants hold.** Admission/isolation, the chat loop, `conversation_id`
   continuity, markdown safety, the lead form's consent gate + honest failure, and the schedule CTA's
   honest availability + no-double-book + honest failure all still behave exactly as before; `tenant_id`
   is still never sent; the visitor token + `conversation_id` + mute preference are all in memory only
   (check `document.cookie`/`localStorage`/`sessionStorage` — none contain any of them).

## S14.6 walkthrough steps (spec Tests section — run all 7)

Run these against the same running backend + host page as above (S14.1's–S14.5's steps still apply as
regressions — see step 7 below). No new preconditions beyond S14.5's. Additional tools/actions needed:
the ability to **stop and start the local backend process** on purpose, and the ability to **hammer
`POST /widget/session`** past its rate limit on purpose (reload the host page repeatedly, or script
requests against it).

**Load-bearing caveat, confirmed by reading the actual backend code (not assumed):** rate limiting today
is enforced **only** on `POST /widget/session` (admission) and the auth routes
(`services/api/src/api/gateway/routes.py`, `widget_session_rate_limit_max = 30` / `window = 60s`,
`config.py:36-37`) — **not** on `/public/chat/message`, `/public/leads`, or `/public/schedule/book`. So a
live `429` is only producible at admission today (step 2 below); turn/lead/booking `429`s are proven by
unit test only, against the real envelope shape, until per-turn metering (SR-1.2) lands. Separately, the
gateway's CORS (`services/api/src/api/edge.py`, `apply_cors_headers`) does **not** send
`Access-Control-Expose-Headers: Retry-After` — so `response.headers.get('Retry-After')` returns `null`
from the widget's `fetch` calls even though the server did send the header. This is real and verified,
not a bug in this sprint's code — the widget is designed to work honestly without it (conservative
generic backoff) and to automatically start honoring the exact value if that one-line backend CORS
change lands later (flagged as a recommended follow-up, out of scope for this frontend-only sprint — see
`dev_plan/sprints/S14.6.md`'s Open questions).

1. **Boot reconnect.** Stop the backend process. Open (or reload) the host page. The widget should show a
   **retrying** connection-status line in the panel header once the panel is opened (a transient boot
   admission failure auto-retries bounded — decision 2), and DevTools Network tab shows a **bounded**
   number of `POST /widget/session` attempts (the default cap is 4) with **increasing gaps** between them
   (exponential backoff + jitter), **not** a tight loop. After the cap is hit, it honestly stops — no
   placeholder/panel UI (or, with `data-debug="true"`, the diagnostic strip only — never a working chat
   UI). **Start the backend**, then reload the page (or use the widget's own boot retry if it's still
   within its window) — it connects normally.
2. **Live `429` at admission (the only live-producible `429` today).** With the backend running, trigger
   the admission rate limit by reloading the host page repeatedly (or scripting requests) past **30
   requests / 60 seconds** to `POST /widget/session` (`config.py:36-37`). Confirm: the response is a real
   `429` with error envelope `{ error_code: "RATE_LIMITED", message, correlation_id }` and (inspect the raw
   response in the Network tab) a `Retry-After` header **is present** on the wire. But confirm in the
   console that `response.headers.get('Retry-After')` returns `null` from JS (the documented cross-origin
   gap) — so the widget's own status copy is the honest, generic "too many requests, retrying shortly"
   (not a specific server-timed number it couldn't actually read). Confirm the widget does **not** retry
   admission before its own conservative backoff window has elapsed.
3. **Transient turn failure → bounded retry → honest offline.** With the backend running and a
   conversation open, mid-conversation stop a dependency the turn call needs (or stop the backend
   entirely) and send a message. Confirm: a **retrying** connection-status line appears in the panel
   header, the Network tab shows a **bounded** number of `POST /public/chat/message` attempts (increasing
   gaps, no storm), then — once the cap is hit — an **offline** status with a visible manual **Retry**
   button, and **no fabricated bot reply** ever appears (check the message list — only the optimistic user
   bubble and the honest error line, no bot bubble). Restore the backend/dependency, click **Retry** — the
   turn succeeds and a real bot reply appears.
4. **Expired-session reconnect.** Leave the panel idle past the visitor token's TTL (30 minutes — or use a
   short-TTL build/local override if you have one) and then send a message. Confirm: an honest
   **"Your session expired — reconnecting…"** status appears, the Network tab shows a **bounded** number
   of re-mint `POST /widget/session` calls (at most 2 — never a loop, and never enough to itself trip the
   admission rate limit from step 2), and then either (a) the re-mint succeeds and an honest "session
   reconnected, please send your message again" line appears (no fabricated reply for the *original*
   failed send), or (b) the re-mint also fails and an honest "please reload the page to continue" status
   appears. Confirm no unbounded re-mint storm against the rate-limited admission endpoint (watch the
   Network tab count).
5. **Honest copy + no fake success.** Across steps 1-4, confirm the visitor-facing connection-status copy
   is friendly and jargon-free ("We can't reach chat right now", "You're sending messages a bit fast…",
   "Your session expired…") and **never** shows a raw `error_code` or `correlation_id` (open the console —
   those stay there, in the `[chatbot-widget] turn failed: ...` / `admission failed: ...` log lines, never
   in the visible UI). Confirm the widget **never** shows a bot reply, a lead success confirmation, or a
   booking confirmation for a failed action anywhere in this walkthrough.
6. **Turn/lead/booking `429` not-yet-producible note.** There is no live way to produce a `429` on
   `POST /public/chat/message`, `POST /public/leads`, or `POST /public/schedule/book` today — no backend
   metering exists yet on those routes (SR-1.2, not landed). This is expected, not a gap in this sprint:
   the widget's `429`/`RATE_LIMITED` handling is built to the same real envelope shape the admission `429`
   uses, and is proven for those three routes by the unit suite's retry-after-parsing tests
   (`turn.test.ts` / `lead.test.ts` / `schedule.test.ts`) plus `retry.test.ts`'s injected-clock assertions
   — only the admission path (step 2) is live-exercisable until SR-1.2 lands.
7. **Regression — S14.1–S14.5 invariants hold.** Re-run S14.5's step 6 regressions (which fold in
   S14.1–S14.4): admission/isolation, the chat loop, `conversation_id` continuity, markdown safety, the
   lead-form consent gate + honest failure, the schedule CTA's honest availability + no-double-book, and
   S14.5's a11y (keyboard/focus/announcements/contrast/TTS) all still behave exactly as before. Additionally
   confirm: `tenant_id` is still never sent in any request (check the Network tab across every scenario
   above); the visitor token, `conversation_id`, and all S14.6 retry/status state remain in memory only
   (check `document.cookie`/`localStorage`/`sessionStorage` — none contain any of them, and a reload always
   starts fresh); and — the S14.6-specific zombie-retry check — open DevTools Network tab, trigger a
   transient turn failure (step 3) so a retry is scheduled, then **close the chat panel** (or navigate away
   from the host page) while the retry is still pending, and confirm **no further `POST /public/chat/
   message` request fires** after the close (the unit suite's `ChatWidget.test.tsx` zombie-timer test
   proves this precisely; this step is the live confirmation).

## SR-3 walkthrough steps (spec Tests section — run all 6)

Run these against the same running backend + host page as above (S14.1's–S14.6's steps still apply as
regressions — see step 6 below). **Additional precondition beyond S14.6's: `widget_session_resume` must be
enabled for the tenant behind this page's client key.** SR-3 rides the existing `tenant_bot_settings`
table (S12.2) — no new column, no migration — reading the boolean key `widget_session_resume` out of that
row's `business_hours` JSON (`api/gateway/repository.py#get_resume_enabled`). To enable it locally: upsert
a `tenant_bot_settings` row for your tenant with `business_hours` containing
`{"widget_session_resume": true}` (via the admin API's `PUT /admin/settings`, or a direct SQL update in
your local dev DB — merge into any existing `business_hours` JSON you already have, don't clobber real
business-hours data if you're also testing that).

1. **Happy resume.** With `npm run dev` running and `widget_session_resume` **enabled**, open `dev/host.html`
   and send a message — normal user + bot bubbles, same as S14.2's happy path. Note the `conversation_id` in
   the Network tab's `POST /public/chat/message` response. Open DevTools' Application/Storage tab and confirm
   `sessionStorage["cw:resume:v1"]` now exists, and its JSON contains **only** the four keys `{token,
   expiresAt, conversationId, lastActive}` — **no** `tenant_id`, name, email, phone, or message text.
2. **Reload reuses the token (the fix).** Reload the page. The Network tab shows **no** new
   `POST /widget/session` request (the console instead logs `[chatbot-widget] resumed session from
   sessionStorage, conversation_id=...`). Send a follow-up message — its request body's `conversation_id`
   matches step 1's value exactly. Check the admin console's conversations list: this is **one** growing
   thread, not a second 2-message fragment — the product debt this sprint fixes.
3. **Same-tab navigation resumes; a new tab does not (decision 3).** Open a second copy of `dev/host.html`
   in the **same browser tab** (e.g. via a link/back-forward, not a new tab) — the widget resumes the same
   conversation (`sessionStorage` is same-tab, same-origin). Now open `dev/host.html` in a **brand-new tab**
   — it starts a fresh session/conversation (no `sessionStorage` record is visible cross-tab); confirm no
   `POST /widget/session` savings there — a full fresh mint happens, exactly like step 1.
4. **Inactivity expiry (decision 5).** Wait more than 15 minutes without sending a message (or temporarily
   lower `TTL_MS` in `src/resume.ts` for a faster local check, then revert it), then reload. The console
   shows a normal fresh mint (no "resumed session" log line), `sessionStorage["cw:resume:v1"]` is gone, and
   the panel starts a genuinely **new**, empty conversation — never a stale/fabricated history.
5. **Stale/foreign handle -> RESUME_REJECTED, never a cross-visitor read (decision 7 — the isolation
   guarantee).** With a resumed session in `sessionStorage` (repeat step 1 to get one), open DevTools and
   hand-edit `sessionStorage["cw:resume:v1"]`'s `conversationId` to a garbage/foreign value (e.g.
   `"deadbeefdeadbeefdeadbeefdeadbeef"`), reload, then send a message. Confirm: the widget shows **no**
   error bubble, the console logs `RESUME_REJECTED` (via the `[chatbot-widget] resume rejected
   (RESUME_REJECTED): ...` line), the Network tab shows the first `POST /public/chat/message` return `404
   CONVERSATION_NOT_FOUND`, immediately followed by a **second** request with `conversation_id: null` that
   succeeds with a **real** reply — and the admin console shows this turn landed in a **brand-new**
   conversation, never inside the foreign/garbage thread you can't actually own. This is the live proof of
   this sprint's core security claim: a persisted-then-swapped `conversation_id` can never resume (or read)
   another visitor's conversation.
6. **Opt-out regression — `widget_session_resume` off is byte-for-byte S14.1/S14.2 (decision 1/8).** Point
   the widget at a tenant with `widget_session_resume` **disabled** (or unset — the default) and repeat
   steps 1–2. Confirm: `sessionStorage["cw:resume:v1"]` is **never** written (check after every send and
   every reload), `document.cookie`/`localStorage` also stay empty of the token, every reload performs a
   fresh `POST /widget/session` mint, and every reload starts a brand-new (empty) conversation — exactly
   S14.1/S14.2's shipped behavior, with zero storage and zero code-path difference a visitor could observe.

## Notes

- `host.html` loads `src/entry.tsx` directly via Vite's dev server (`type="module"`) for fast iteration —
  this is different from the production embed, which loads the built `dist/widget.js` IIFE. Both paths
  exercise the same `config.ts` / `session.ts` / `turn.ts` / `lead.ts` / `schedule.ts` / `mount.tsx` /
  `entry.tsx` logic; only the packaging differs. To test against the actual production bundle instead, run
  `npm run build` and swap the `<script>` tag to
  `<script src="/dist/widget.js" data-client-key="..." ...></script>` (no `type="module"`, since the build
  output is an IIFE, not an ES module) served via any static file server.
- This page and this README are dev-only conveniences under `apps/widget/dev/` — no `services/**` or
  `deploy/**` file is touched by S14.1, S14.2, S14.3, S14.4, S14.5, or S14.6.
- S14.4 did not add rescheduling/cancellation, TTS, the full a11y/WCAG pass, 429/`Retry-After` UX, or
  per-tenant consent/slot-window config — TTS + the a11y/WCAG pass landed in S14.5, and 429/`Retry-After`
  UX + connection-status/reconnect landed in S14.6 (see their walkthroughs above); rescheduling/
  cancellation and per-tenant consent/slot-window config remain flagged follow-ups beyond Phase 14. The
  consent `purpose`/`text` shown in the schedule CTA's checkbox are fixed client-side constants for now
  (see `src/schedule.ts`), separate from — but colocated in pattern with — the lead form's constants in
  `src/lead.ts`.
- S14.5's TTS greeting text is a baked-in client constant (`TTS_GREETING_TEXT` in `src/tts.ts`), not
  server-driven/per-tenant/localized — that's a flagged future item, not a bug in this walkthrough. The
  mute preference is in-memory only (no `localStorage`) — it resets on every page reload by design.
- **S14.6, the sixth and final sprint of Phase 14, closes the phase's implementation** (all six sprints
  now IN REVIEW awaiting their host-page live passes — see each sprint file's status line). Two flagged
  follow-ups, explicitly out of scope for S14.6 and named in `dev_plan/sprints/S14.6.md`'s Open questions:
  (1) the one-line backend CORS change `Access-Control-Expose-Headers: Retry-After` in
  `services/api/src/api/edge.py`'s `apply_cors_headers` — this would make the real server `Retry-After`
  value readable cross-origin and let the widget honor the exact server timing everywhere instead of its
  conservative generic backoff (S14.6 works correctly without it and will automatically start using the
  exact value if/when it lands — no widget change needed); (2) per-turn metering /
  `TURN_BUDGET_EXCEEDED` on `/public/chat/message` (SR-1.2) — a backend concern that, when it lands, needs
  no widget change either, since the `429`/`RATE_LIMITED` handling is already built to the real envelope
  shape and only needs a live-producible turn `429` to exercise end-to-end (today only the admission `429`
  is live-producible — walkthrough step 2/6 above).
