"use client";

/**
 * Upload form + live status panel (S13.3 decisions 3-6), restyled to the
 * locked 5a design (knowledge_base/ui design/updated ui/project/HANDOFF-SPEC.md
 * §3, `Chatbot System Designs.dc.html#5a`) -- dashed dropzone, status badges,
 * ink "Coverage check" card, "Test the bot" card.
 *
 * All upload/polling logic below is unchanged from the original: the form is
 * a real `<form action={uploadKnowledge}>` posting a `File` via `FormData`
 * -- the file moves server->server (this component's `onSubmit` only does a
 * courtesy client-side pre-check, decision 5, and never touches `admin-api`
 * directly). Once the action returns an `uploaded` state, this component
 * switches to `StatusPanel`, which polls `getDocStatus` every 2.5s, stops on
 * a terminal run state (`succeeded`/`failed`) or an error, and caps
 * automatic polling at 120 attempts (~5 minutes) with a manual "Refresh
 * status" fallback (decision 4) -- so a doc stuck at `queued` because no
 * Celery worker is running never spins forever.
 *
 * Backend reality check (2026-07-19 restyle): the 5a mock shows a
 * multi-source table with INDEXED/PROCESSING/FAILED badges and a chunk
 * count column. The real backend (services/api/src/api/ingestion/routes.py)
 * has no list endpoint -- only `GET /admin/ingestion/docs/{doc_id}`, one
 * document at a time -- and no chunk count in its response payload
 * (`chunks_out` is dropped before the API boundary). The real `doc.status`
 * enum is `pending`/`parsed`/`failed` (not `INDEXED`/`PROCESSING`/`FAILED`);
 * `run.status` is `queued`/`running`/`succeeded`/`failed`. This component
 * therefore renders a single-source status card styled per the 5a table row
 * recipe rather than fabricating a multi-row table the backend can't back.
 * "Coverage check" and "Test the bot" have no backend behind them at all
 * (see `CoverageCheckCard`/`TestBotCard` below) -- both render honest
 * unavailable/coming-soon states, not invented data.
 */
import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";
import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  getDocStatus,
  uploadKnowledge,
  type DocStatusResult,
  type UploadState,
} from "@/app/(protected)/knowledge/actions";
import {
  ALLOWED_CONTENT_TYPES,
  ALLOWED_EXTENSIONS,
  FILE_INPUT_ACCEPT,
  MAX_UPLOAD_BYTES,
  formatBytes,
  formatRunErrors,
  isTerminalRunStatus,
  schedulePolling,
  statusBadge,
  badgeToneClassName,
} from "@/lib/knowledge-constants";
import { cn } from "@/lib/utils";

const initialState: UploadState = { status: "idle" };

const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 120; // ~5 minutes at 2.5s/poll (decision 4).

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button
      type="submit"
      disabled={pending}
      className="h-11 w-full rounded-[9px] bg-[#191a17] font-bold text-[#e4f222] hover:bg-[#191a17]/90 disabled:opacity-60"
    >
      {pending ? "Uploading…" : "Upload document"}
    </Button>
  );
}

/**
 * Client-side pre-check mirroring (not replacing) the backend's real
 * size/content-type gate. Returns an error message, or `null` if the file
 * looks acceptable and the submit should proceed.
 */
function precheckFile(file: File): string | null {
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is too large (${formatBytes(file.size)}). The limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`;
  }

  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  const extensionOk = (ALLOWED_EXTENSIONS as readonly string[]).includes(extension);

  const normalizedType = file.type.split(";")[0].trim().toLowerCase();
  // Some browsers/OSes mislabel .docx as application/octet-stream (a known,
  // flagged gap -- see S13.3.md's Flagged gaps §3): don't hard-fail on a
  // blank/unrecognized MIME type if the extension is right; let the backend
  // be the final word either way.
  const typeOk = normalizedType === "" || (ALLOWED_CONTENT_TYPES as readonly string[]).includes(normalizedType);

  if (!extensionOk || !typeOk) {
    return `Unsupported file type. Only ${ALLOWED_EXTENSIONS.join(", ")} files are accepted.`;
  }

  return null;
}

function StatusPanel({
  docId,
  initialRunId,
  initialDocStatus,
  idempotent,
  tenantId,
}: {
  docId: string;
  initialRunId: string | null;
  initialDocStatus: string;
  idempotent: boolean;
  tenantId?: string;
}) {
  const [result, setResult] = useState<DocStatusResult | null>(null);
  const [cappedOut, setCappedOut] = useState(false);

  const runStatus =
    result?.status === "ok" ? (result.run?.status ?? "queued") : null;
  const hasError = result?.status === "error";
  const terminal = hasError || (runStatus !== null && isTerminalRunStatus(runStatus));

  // Polling driver (decision 4): calls getDocStatus every POLL_INTERVAL_MS,
  // stopping itself once a terminal run state/error is reached, or after
  // MAX_POLLS attempts (the "worker may be down" cap). Extracted as a pure
  // function (lib/knowledge-constants.ts) so this stop-on-terminal/cap
  // behavior is unit-testable with fake timers.
  useEffect(() => {
    const stop = schedulePolling<DocStatusResult>({
      pollOnce: () => getDocStatus(docId, tenantId),
      isTerminal: (r) => r.status === "error" || (r.status === "ok" && isTerminalRunStatus(r.run?.status ?? "queued")),
      onResult: (r) => setResult(r),
      onCapped: () => setCappedOut(true),
      intervalMs: POLL_INTERVAL_MS,
      maxPolls: MAX_POLLS,
    });
    return stop;
  }, [docId, tenantId]);

  // Manual "Refresh status" -- fires a one-off poll outside the driver
  // (safe post-cap or pre-cap alike); does not re-arm automatic polling.
  function manualRefresh() {
    void getDocStatus(docId, tenantId).then(setResult);
  }

  const docStatus = result?.status === "ok" ? result.docStatus : initialDocStatus;
  const badge = statusBadge(docStatus, runStatus);

  return (
    <div className="flex flex-col gap-4">
      {/* Source row styled per HANDOFF-SPEC.md §3 "5a" sources table (header
          #f7f7f3 uppercase muted, row w/ SOURCE/STATUS columns). Rendered as
          a single-row card, not a fabricated multi-row table -- the backend
          has no list endpoint (GET /admin/ingestion/docs/{doc_id} only,
          services/api/src/api/ingestion/routes.py:223-239) so there is no
          real data source for additional rows. */}
      <div className="overflow-hidden rounded-[14px] border border-[#e7e7e2]">
        <div className="grid grid-cols-[2fr_1fr_auto] bg-[#f7f7f3] px-3.5 py-2.5 text-[11.5px] font-semibold tracking-[0.02em] text-[#70716a] uppercase">
          <span>Source</span>
          <span>Status</span>
          <span className="text-right">Action</span>
        </div>
        <div
          className={cn(
            "grid grid-cols-[2fr_1fr_auto] items-center gap-2 px-3.5 py-3.5",
            badge.tone === "failed" && "bg-[#fdfdec]"
          )}
        >
          <span className="min-w-0 truncate text-[13px] font-bold text-[#191a17]">
            Uploaded document
          </span>
          <span>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10.5px] font-bold whitespace-nowrap",
                badgeToneClassName(badge.tone)
              )}
            >
              {badge.tone === "success" ? "●" : badge.tone === "failed" ? "✕" : "◌"} {badge.label.toUpperCase()}
            </span>
          </span>
          <span className="text-right">
            {badge.tone === "failed" ? (
              <button
                type="button"
                onClick={() =>
                  window.location.assign(tenantId ? `/clients/${tenantId}/knowledge` : "/knowledge")
                }
                className="min-h-11 rounded-[9px] px-2 text-[11.5px] font-semibold text-[#191a17] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
              >
                Retry ↻
              </button>
            ) : null}
          </span>
        </div>
      </div>

      {idempotent ? (
        <p
          role="status"
          className="rounded-[9px] border border-[#e7e7e2] bg-[#fbfbf8] p-3 text-[12.5px] text-[#45463f]"
        >
          This exact file is already ingested (identical content) -- no new run was started.
          Current status: <span className="font-semibold text-[#191a17]">{docStatus}</span>.
        </p>
      ) : null}

      {hasError ? (
        <p
          role="alert"
          className="rounded-[9px] border border-[#c2452d]/30 bg-[#f6e3df] p-3 text-[12.5px] font-medium text-[#c2452d]"
        >
          {result.status === "error" ? result.message : "Unable to load status."}
        </p>
      ) : (
        <RunStatusBody
          runId={result?.status === "ok" ? (result.run?.runId ?? initialRunId) : initialRunId}
          status={runStatus ?? "queued"}
          charsOut={result?.status === "ok" ? (result.run?.charsOut ?? null) : null}
          durationMs={result?.status === "ok" ? (result.run?.durationMs ?? null) : null}
          errors={result?.status === "ok" ? (result.run?.errors ?? null) : null}
          parsedPreview={result?.status === "ok" ? result.parsedPreview : null}
        />
      )}

      {cappedOut ? (
        <p
          role="alert"
          className="rounded-[9px] border border-[#f0e2bd] bg-[#fff9ec] p-3 text-[12.5px] text-[#6a4e00]"
        >
          Still processing after 5 minutes -- the ingestion worker may be busy or down. This
          document&apos;s status is <span className="font-semibold">{runStatus ?? "queued"}</span>;
          check back later.
        </p>
      ) : null}

      <div className="flex gap-2">
        {!terminal ? (
          <button
            type="button"
            onClick={manualRefresh}
            className="min-h-11 rounded-[9px] border border-[#e7e7e2] bg-white px-3.5 text-[12.5px] font-semibold text-[#45463f] hover:bg-[#f7f7f3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
          >
            Refresh status
          </button>
        ) : null}
        <button
          type="button"
          onClick={() =>
            window.location.assign(tenantId ? `/clients/${tenantId}/knowledge` : "/knowledge")
          }
          className={cn(
            "min-h-11 rounded-[9px] px-3.5 text-[12.5px] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]",
            terminal
              ? "bg-[#191a17] text-[#e4f222] hover:bg-[#191a17]/90"
              : "text-[#70716a] hover:bg-[#f7f7f3]"
          )}
        >
          Upload another
        </button>
      </div>
    </div>
  );
}

function RunStatusBody({
  status,
  charsOut,
  durationMs,
  errors,
  parsedPreview,
}: {
  runId: string | null;
  status: string;
  charsOut: number | null;
  durationMs: number | null;
  errors: unknown;
  parsedPreview: string | null;
}) {
  if (status === "queued") {
    return (
      <p role="status" className="animate-pulse text-[13px] text-[#45463f]">
        Queued for ingestion…
      </p>
    );
  }

  if (status === "running") {
    return (
      <p role="status" className="animate-pulse text-[13px] text-[#45463f]">
        Processing -- parsing, chunking, and embedding… Larger documents can take a few minutes.
      </p>
    );
  }

  if (status === "succeeded") {
    return (
      <div className="flex flex-col gap-2">
        <p role="status" className="text-[13px] font-semibold text-[#1f6a2f]">
          Ingested successfully.
        </p>
        {charsOut !== null ? (
          <p className="text-[12.5px] text-[#70716a]">{charsOut.toLocaleString()} characters extracted.</p>
        ) : null}
        {parsedPreview ? (
          <div className="flex flex-col gap-1">
            <Label className="text-[12px] font-semibold text-[#45463f]">Content preview</Label>
            <p className="max-h-40 overflow-y-auto rounded-[9px] border border-[#e7e7e2] bg-[#fbfbf8] p-2.5 text-[12.5px] whitespace-pre-wrap text-[#191a17]">
              {parsedPreview}
            </p>
          </div>
        ) : null}
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="flex flex-col gap-2">
        <p
          role="alert"
          className="rounded-[9px] border border-[#c2452d]/30 bg-[#f6e3df] p-3 text-[12.5px] font-semibold text-[#c2452d]"
        >
          Ingestion failed.
        </p>
        <pre className="max-h-40 overflow-y-auto rounded-[9px] border border-[#c2452d]/30 bg-[#f6e3df] p-2.5 text-xs whitespace-pre-wrap text-[#c2452d]">
          {formatRunErrors(errors)}
        </pre>
        {durationMs !== null ? (
          <p className="text-xs text-[#70716a]">Run duration: {durationMs}ms</p>
        ) : null}
      </div>
    );
  }

  // Defensive fallback for any status value we don't otherwise recognize --
  // never a blank/silent panel.
  return <p className="text-[13px] text-[#70716a]">Status: {status}</p>;
}

/**
 * Dashed dropzone per HANDOFF-SPEC.md §3 "5a" (`border-dashed` #d5d5cb,
 * radius 14, `paper`-tinted background). Drag-and-drop is a progressive
 * enhancement only: the zone itself is a real, keyboard-operable
 * `<button>` that opens the underlying `<input type="file">` (a11y
 * requirement -- ui-ux-pro-max §1/§2 -- dropzones must have a non-drag
 * fallback), and the input also stays independently reachable so a screen
 * reader or keyboard-only user never depends on drag gestures.
 */
function Dropzone({
  fileInputId,
  selectedFileName,
  onFilesChosen,
  isDragActive,
  onDragStateChange,
}: {
  fileInputId: string;
  selectedFileName: string | null;
  onFilesChosen: (files: FileList | null) => void;
  isDragActive: boolean;
  onDragStateChange: (active: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    onDragStateChange(false);
    onFilesChosen(event.dataTransfer.files);
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        onDragStateChange(true);
      }}
      onDragLeave={() => onDragStateChange(false)}
      onDrop={handleDrop}
      className={cn(
        "flex flex-col items-center gap-3 rounded-[14px] border-[1.5px] border-dashed bg-[#fbfbf8] p-6 text-center transition-colors sm:flex-row sm:text-left",
        isDragActive ? "border-[#191a17] bg-[#fdfdec]" : "border-[#d5d5cb]"
      )}
    >
      <div className="grid size-10 shrink-0 place-items-center rounded-[11px] bg-[#eef7a8] text-[17px]">
        ↥
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-bold text-[#191a17]">
          {selectedFileName ? selectedFileName : "Drop a .txt or .docx here"}
        </p>
        <p className="text-[12px] text-[#70716a]">
          Up to {formatBytes(MAX_UPLOAD_BYTES)} · {ALLOWED_EXTENSIONS.join(", ").toUpperCase()}
        </p>
      </div>
      <input
        ref={inputRef}
        id={fileInputId}
        name="file"
        type="file"
        required
        accept={FILE_INPUT_ACCEPT}
        onChange={(event) => onFilesChosen(event.target.files)}
        className="sr-only"
      />
      <label
        htmlFor={fileInputId}
        className="min-h-11 shrink-0 cursor-pointer rounded-[9px] border border-[#e7e7e2] bg-white px-3.5 py-2.5 text-[12px] font-semibold whitespace-nowrap text-[#45463f] hover:bg-[#f7f7f3] focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[#191a17]"
      >
        Browse…
      </label>
    </div>
  );
}

/**
 * `tenantId` (S13.7): when provided, the per-client knowledge screen renders
 * this same form binding `uploadKnowledge` to the S12.7 tenant-scoped upload
 * route (`uploadKnowledge.bind(null, tenantId)`) -- reused as-is, not
 * rewritten. `undefined` preserves the existing CLIENT_ADMIN behavior.
 */
export function UploadForm({ tenantId }: { tenantId?: string } = {}) {
  const [state, formAction] = useActionState(uploadKnowledge.bind(null, tenantId), initialState);
  const [clientError, setClientError] = useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const fileInputId = useId();

  function applyFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;

    // Reflect a dropped/browsed file into the real <input type="file"> so
    // the form submission (and the existing precheck/server-action path)
    // work unchanged whether the file arrived via drag or Browse….
    const input = formRef.current?.elements.namedItem("file");
    if (input instanceof HTMLInputElement) {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
    }
    setSelectedFileName(file.name);
    setClientError(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    const input = event.currentTarget.elements.namedItem("file");
    const file = input instanceof HTMLInputElement ? input.files?.[0] : undefined;

    if (!file) {
      event.preventDefault();
      setClientError("Choose a .txt or .docx file to upload.");
      return;
    }

    const error = precheckFile(file);
    if (error) {
      event.preventDefault();
      setClientError(error);
      return;
    }

    setClientError(null);
  }

  if (state.status === "uploaded") {
    return (
      <StatusPanel
        docId={state.docId}
        initialRunId={state.runId}
        initialDocStatus={state.docStatus}
        idempotent={state.idempotent}
        tenantId={tenantId}
      />
    );
  }

  return (
    <form ref={formRef} action={formAction} onSubmit={handleSubmit} className="flex flex-col gap-4">
      <Dropzone
        fileInputId={fileInputId}
        selectedFileName={selectedFileName}
        onFilesChosen={applyFiles}
        isDragActive={isDragActive}
        onDragStateChange={setIsDragActive}
      />

      {clientError ? (
        <p role="alert" className="text-[12.5px] font-medium text-[#c2452d]">
          {clientError}
        </p>
      ) : null}

      {state.status === "error" ? (
        <p role="alert" className="text-[12.5px] font-medium text-[#c2452d]">
          {state.message}
        </p>
      ) : null}

      <SubmitButton />
    </form>
  );
}

/**
 * "Coverage check" card per HANDOFF-SPEC.md §3 "5a" (ink background,
 * unanswered questions ×count list, citron "Answer these →" CTA).
 *
 * NO BACKEND EXISTS for this today: grepped
 * services/api/src/api/{ingestion,rag,orchestrator,conversation_store}/**
 * for unanswered/coverage/no_answer/low_confidence/fallback_count/gap --
 * the only hits are internal RAG confidence-scoring variable names
 * (rag/service.py's `w_coverage` term in the confidence formula) and code
 * comments, not an admin-facing endpoint or count. Per CLAUDE.md's
 * no-silent-fallback rule, this renders an honest "not available yet"
 * empty state instead of inventing question text/counts to match the mock.
 * Flagged gap: needs a new backend aggregate (e.g. over low-confidence /
 * fallback-triggering conversation turns) before this card can show real
 * data -- out of scope for this UI-only sprint.
 */
function CoverageCheckCard() {
  return (
    <div className="flex flex-col gap-2.5 rounded-[14px] bg-[#191a17] p-4.5">
      <p className="text-[13px] font-bold text-white">Coverage check</p>
      <p className="text-[11.5px] leading-relaxed text-[#9b9c93]">
        Questions your bot couldn&apos;t answer this week -- add content to fix.
      </p>
      <div
        role="status"
        className="mt-0.5 rounded-[9px] border border-dashed border-[#3d3e38] bg-[#26271f] px-3 py-3 text-[12px] text-[#c6c7bd]"
      >
        Not available yet. This needs a backend endpoint that surfaces low-confidence /
        fallback-triggering questions from conversation history -- it doesn&apos;t exist yet.
      </div>
    </div>
  );
}

/**
 * "Test the bot" card per HANDOFF-SPEC.md §3 "5a" (bordered card, query
 * input, "Run test" pill).
 *
 * NO BACKEND EXISTS for an admin-authenticated ad-hoc query endpoint:
 * services/api/src/api/orchestrator/routes.py exposes exactly two routes,
 * `POST /public/chat/message` and `POST /public/chat/message/stream`, both
 * gated on `get_visitor_claims` (a signed VISITOR session) -- there is no
 * admin/CLIENT_ADMIN-authenticated preview/simulate/sandbox route. Wiring
 * this to the visitor endpoint would be both a scope violation (this
 * sprint is UI-only, no backend/API changes) and a role-model violation
 * (CLIENT_ADMIN using a VISITOR-only route). Renders a disabled "coming
 * soon" state instead of a fabricated bot reply. Flagged gap: needs a new
 * admin-authenticated query-preview endpoint that runs the real RAG/
 * orchestrator pipeline without persisting a conversation.
 */
function TestBotCard() {
  const inputId = useId();
  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-[#e7e7e2] p-4">
      <p className="text-[12.5px] font-bold text-[#191a17]">Test the bot</p>
      <Label htmlFor={inputId} className="sr-only">
        Test question
      </Label>
      <input
        id={inputId}
        type="text"
        disabled
        placeholder="Ask a question to preview the answer…"
        aria-describedby={`${inputId}-hint`}
        className="min-h-11 rounded-[9px] border border-[#e7e7e2] px-3 text-[12px] text-[#96978e] disabled:cursor-not-allowed disabled:bg-[#fbfbf8]"
      />
      <button
        type="button"
        disabled
        className="min-h-11 w-fit self-start rounded-full border border-[#e7e7e2] px-3 text-[11.5px] font-semibold text-[#a8a99f] disabled:cursor-not-allowed"
      >
        Run test
      </button>
      <p id={`${inputId}-hint`} className="text-[11px] text-[#96978e]">
        Coming soon -- needs an admin-authenticated query-preview endpoint (not built yet; the
        only live query path today is the visitor widget&apos;s session-gated chat endpoint).
      </p>
    </div>
  );
}

export { CoverageCheckCard, TestBotCard };
