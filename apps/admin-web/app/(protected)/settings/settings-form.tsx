"use client";

/**
 * Tenant bot-settings edit form (S13.6 decisions 1, 4-7). A thin client
 * component pre-populated from the server-loaded `currentSettings`, wired to
 * the `"use server"` `saveSettings` action via `useActionState`. Renders a
 * read-only view when `canEdit` is false (defensive -- the page only mounts
 * this for CLIENT_ADMIN; a CLIENT_AGENT gets `ReadOnlySettings` directly, see
 * page.tsx).
 *
 * Bug fix (post-S13.6): the fields are CONTROLLED, not uncontrolled
 * `defaultValue`s. Previously each `Textarea`/`Input` used
 * `defaultValue={displaySettings.field}` where `displaySettings` fell back to
 * `currentSettings` (the ORIGINAL server-loaded value) on every non-"saved"
 * render -- including error <-> error re-renders. Because the inputs are
 * Base UI `Field.Control`s (`components/ui/input.tsx` wraps
 * `@base-ui/react/input`), which read `defaultValue` once and warn in dev if
 * it changes on a later render, this produced the "changing the default
 * value state of an uncontrolled FieldControl" console warning -- the
 * visible symptom of the same root cause described below. See
 * `lib/settings-schema.ts`'s `shouldResetFieldsToServerValues` doc comment
 * for the full analysis. Controlled state here is seeded once on mount from
 * `currentSettings`, and is only overwritten with the server's fresh values
 * on a genuine NEW "saved" transition (preserving decision 4: confirmed, not
 * optimistic) -- never on an error re-render, so in-progress edits made
 * between two failed submissions survive.
 */
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { saveSettings, type SaveState } from "@/app/(protected)/settings/actions";
import {
  fieldValuesFromSettings,
  shouldResetFieldsToServerValues,
} from "@/lib/settings-schema";
import type { BotSettings } from "@/lib/settings";

const initialState: SaveState = { status: "idle" };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "Saving..." : "Save settings"}
    </Button>
  );
}

export function SettingsForm({
  currentSettings,
}: {
  currentSettings: BotSettings;
}) {
  const [state, formAction] = useActionState(saveSettings, initialState);

  // Controlled field state, seeded once from the server-loaded snapshot.
  // `useState`'s lazy initializer only runs on mount, so this does NOT
  // re-derive on every render -- that's the whole point (see file-header
  // comment and `shouldResetFieldsToServerValues`'s doc comment).
  const [fields, setFields] = useState(() => fieldValuesFromSettings(currentSettings));

  // Track the previous `state` reference so we can detect a genuine NEW
  // "saved" transition during render (React's documented "adjusting state
  // during render" pattern -- avoids an extra effect-driven render/flash and
  // avoids re-running on unrelated parent re-renders, since `state` is only
  // a new object when `useActionState` produces a new result).
  const [prevState, setPrevState] = useState(state);
  if (shouldResetFieldsToServerValues(prevState, state)) {
    // `state.status === "saved"` is guaranteed by
    // `shouldResetFieldsToServerValues`, but narrow explicitly for TS.
    if (state.status === "saved") {
      setFields(fieldValuesFromSettings(state.settings));
    }
    setPrevState(state);
  } else if (prevState !== state) {
    setPrevState(state);
  }

  const fieldErrors = state.status === "error" ? state.fieldErrors : {};
  const formError = state.status === "error" ? state.formError : null;

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {state.status === "saved" ? (
        <p role="status" className="rounded-md border border-input bg-muted/50 p-3 text-sm">
          Saved.
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <Label htmlFor="greeting">Greeting</Label>
        <Textarea
          id="greeting"
          name="greeting"
          value={fields.greeting}
          onChange={(e) => setFields((f) => ({ ...f, greeting: e.target.value }))}
          maxLength={2000}
          rows={3}
          placeholder="Hi! How can I help you today?"
        />
        {fieldErrors.greeting ? (
          <p role="alert" className="text-sm text-destructive">
            {fieldErrors.greeting}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">Up to 2000 characters.</p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="businessHoursText">Business hours (JSON)</Label>
        <Textarea
          id="businessHoursText"
          name="businessHoursText"
          value={fields.businessHoursText}
          onChange={(e) =>
            setFields((f) => ({ ...f, businessHoursText: e.target.value }))
          }
          rows={6}
          className="font-mono text-sm"
          placeholder={'{\n  "mon": ["09:00", "17:00"]\n}'}
        />
        {fieldErrors.businessHoursText ? (
          <p role="alert" className="text-sm text-destructive">
            {fieldErrors.businessHoursText}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            A JSON object, e.g. {"{"}&quot;mon&quot;: [&quot;09:00&quot;, &quot;17:00&quot;]{"}"} —
            or leave blank.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="escalationPolicy">Escalation policy</Label>
        <Textarea
          id="escalationPolicy"
          name="escalationPolicy"
          value={fields.escalationPolicy}
          onChange={(e) =>
            setFields((f) => ({ ...f, escalationPolicy: e.target.value }))
          }
          maxLength={2000}
          rows={3}
          placeholder="Escalate to a human agent when the visitor asks for a refund."
        />
        {fieldErrors.escalationPolicy ? (
          <p role="alert" className="text-sm text-destructive">
            {fieldErrors.escalationPolicy}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">Up to 2000 characters.</p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="tone">Tone</Label>
        <Input
          id="tone"
          name="tone"
          value={fields.tone}
          onValueChange={(value) => setFields((f) => ({ ...f, tone: value }))}
          maxLength={100}
          placeholder="friendly, professional, concise"
        />
        {fieldErrors.tone ? (
          <p role="alert" className="text-sm text-destructive">
            {fieldErrors.tone}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Free text (up to 100 characters) — e.g. &quot;friendly&quot;, &quot;professional&quot;,
            &quot;concise&quot;. Not restricted to a fixed list.
          </p>
        )}
      </div>

      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <SubmitButton />
    </form>
  );
}
