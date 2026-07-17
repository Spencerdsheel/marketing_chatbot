"use client";

/**
 * D7 rotate-key control, rendered in the per-client layout header. Binds
 * `rotateKeyForClient` to this screen's `tenantId` (the route segment,
 * never client state -- D1) via `.bind(null, tenantId)`, the same pattern
 * `upload-form.tsx` uses for `uploadKnowledge`.
 *
 * Secrets hygiene: the fresh one-time `clientKey` lives only in this
 * component's React state (from the server action's return value) -- never
 * written to a cookie, `localStorage`, the URL, or `console`. A confirm step
 * guards against an accidental click (rotating immediately invalidates the
 * old key).
 */
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { rotateKeyForClient, type RotateKeyState } from "@/app/(protected)/clients/actions";

const initialState: RotateKeyState = { status: "idle" };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      {pending ? "Rotating..." : "Rotate client key"}
    </Button>
  );
}

function CopyButton({ value }: { value: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "unavailable">("idle");

  async function handleCopy() {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
        setStatus("copied");
        setTimeout(() => setStatus("idle"), 2000);
        return;
      } catch {
        // fall through
      }
    }
    setStatus("unavailable");
  }

  return (
    <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
      {status === "copied" ? "Copied!" : "Copy key"}
    </Button>
  );
}

export function RotateKeyControl({ tenantId }: { tenantId: string }) {
  const [state, formAction] = useActionState(rotateKeyForClient.bind(null, tenantId), initialState);
  const [confirming, setConfirming] = useState(false);

  if (state.status === "rotated") {
    return (
      <div className="flex flex-col items-end gap-1.5 rounded-md border border-destructive/40 bg-destructive/5 p-2.5">
        <p role="alert" className="text-xs font-medium text-destructive">
          New key — shown once, not recoverable later.
        </p>
        <div className="flex items-center gap-2">
          <code className="select-all overflow-x-auto rounded-md border border-input bg-muted px-2 py-1 text-xs">
            {state.clientKey}
          </code>
          <CopyButton value={state.clientKey} />
        </div>
      </div>
    );
  }

  if (!confirming) {
    return (
      <div className="flex flex-col items-end gap-1">
        <Button type="button" variant="outline" size="sm" onClick={() => setConfirming(true)}>
          Rotate client key
        </Button>
        {state.status === "error" ? (
          <p role="alert" className="text-xs text-destructive">
            {state.message}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form action={formAction} className="flex flex-col items-end gap-1.5">
      <p className="text-xs text-muted-foreground">
        This invalidates the current key immediately. Continue?
      </p>
      <div className="flex gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          Cancel
        </Button>
        <SubmitButton />
      </div>
    </form>
  );
}
