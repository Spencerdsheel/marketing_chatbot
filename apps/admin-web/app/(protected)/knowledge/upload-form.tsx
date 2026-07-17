"use client";

/**
 * Upload form + live status panel (S13.3 decisions 3-6).
 *
 * The form is a real `<form action={uploadKnowledge}>` posting a `File` via
 * `FormData` -- the file moves server->server (this component's `onSubmit`
 * only does a courtesy client-side pre-check, decision 5, and never touches
 * `admin-api` directly). Once the action returns an `uploaded` state, this
 * component switches to `StatusPanel`, which polls `getDocStatus` every
 * 2.5s, stops on a terminal run state (`succeeded`/`failed`) or an error, and
 * caps automatic polling at 120 attempts (~5 minutes) with a manual
 * "Refresh status" fallback (decision 4) -- so a doc stuck at `queued`
 * because no Celery worker is running never spins forever.
 */
import { useEffect, useId, useState, type FormEvent } from "react";
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
} from "@/lib/knowledge-constants";

const initialState: UploadState = { status: "idle" };

const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 120; // ~5 minutes at 2.5s/poll (decision 4).

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" className="w-full" disabled={pending}>
      {pending ? "Uploading..." : "Upload document"}
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

  return (
    <div className="flex flex-col gap-4">
      {idempotent ? (
        <p
          role="status"
          className="rounded-md border border-input bg-muted/50 p-3 text-sm"
        >
          This exact file is already ingested (identical content) -- no new run was started.
          Current status: <span className="font-medium">{result?.status === "ok" ? result.docStatus : initialDocStatus}</span>.
        </p>
      ) : null}

      {hasError ? (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
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
        <p role="alert" className="rounded-md border border-input bg-muted/50 p-3 text-sm">
          Still processing after 5 minutes -- the ingestion worker may be busy or down. This
          document&apos;s status is <span className="font-medium">{runStatus ?? "queued"}</span>;
          check back later.
        </p>
      ) : null}

      <div className="flex gap-2">
        {!terminal ? (
          <Button type="button" variant="outline" onClick={manualRefresh}>
            Refresh status
          </Button>
        ) : null}
        <Button
          type="button"
          variant={terminal ? "default" : "ghost"}
          onClick={() =>
            window.location.assign(tenantId ? `/clients/${tenantId}/knowledge` : "/knowledge")
          }
        >
          Upload another
        </Button>
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
      <p role="status" className="animate-pulse text-sm">
        Queued for ingestion…
      </p>
    );
  }

  if (status === "running") {
    return (
      <p role="status" className="animate-pulse text-sm">
        Processing -- parsing, chunking, and embedding… Larger documents can take a few minutes.
      </p>
    );
  }

  if (status === "succeeded") {
    return (
      <div className="flex flex-col gap-2">
        <p role="status" className="text-sm font-medium text-emerald-600 dark:text-emerald-400">
          Ingested successfully.
        </p>
        {charsOut !== null ? (
          <p className="text-sm text-muted-foreground">{charsOut.toLocaleString()} characters extracted.</p>
        ) : null}
        {parsedPreview ? (
          <div className="flex flex-col gap-1">
            <Label>Content preview</Label>
            <p className="max-h-40 overflow-y-auto rounded-md border border-input bg-muted/50 p-2.5 text-sm whitespace-pre-wrap">
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
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm font-medium text-destructive">
          Ingestion failed.
        </p>
        <pre className="max-h-40 overflow-y-auto rounded-md border border-destructive/40 bg-destructive/5 p-2.5 text-xs whitespace-pre-wrap text-destructive">
          {formatRunErrors(errors)}
        </pre>
        {durationMs !== null ? (
          <p className="text-xs text-muted-foreground">Run duration: {durationMs}ms</p>
        ) : null}
      </div>
    );
  }

  // Defensive fallback for any status value we don't otherwise recognize --
  // never a blank/silent panel.
  return <p className="text-sm text-muted-foreground">Status: {status}</p>;
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
  const fileInputId = useId();

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
    <form action={formAction} onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor={fileInputId}>Document</Label>
        <input
          id={fileInputId}
          name="file"
          type="file"
          required
          accept={FILE_INPUT_ACCEPT}
          className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-muted file:px-2.5 file:py-1 file:text-sm file:font-medium"
        />
        <p className="text-xs text-muted-foreground">
          .txt or .docx, up to {formatBytes(MAX_UPLOAD_BYTES)}.
        </p>
      </div>

      {clientError ? (
        <p role="alert" className="text-sm text-destructive">
          {clientError}
        </p>
      ) : null}

      {state.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      ) : null}

      <SubmitButton />
    </form>
  );
}
