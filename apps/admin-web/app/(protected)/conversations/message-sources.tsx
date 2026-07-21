"use client";

/**
 * Grounding spot-check affordance (SR-2). A plain "View sources (N)" toggle
 * rendered under a bot message that has cited sources (`sourceCount > 0`,
 * gated by the caller in `transcript-pane.tsx`). Expanding it calls the
 * `fetchSourcesAction` Server Function (bound with this conversation's
 * `conversationId`/`tenantId` in `transcript-pane.tsx`, since
 * `lib/conversations.ts` is `import "server-only"` and cannot be imported
 * directly into a client component) and renders the reply text next to each
 * cited chunk's resolved text.
 *
 * Deliberately minimal, per SR-2 decision 10 / the sprint's explicit
 * boundary: no diff, no overlap highlighting, no support/groundedness
 * verdict beyond echoing the stored `score` -- resolve-and-let-a-human-judge
 * is the whole point. An unresolved source renders an honest "source no
 * longer in the knowledge base" line (never blank, never placeholder text --
 * no silent fallback, CLAUDE.md §3).
 *
 * The four pure helper functions (`shouldShowSourcesAffordance`,
 * `sourcesToggleLabel`, `sourceBodyText`, `sourceMetaLabel`) live in
 * `message-sources-presentation.ts`, a plain module with no `"use client"`
 * marker, and are re-exported here for backward compatibility. They moved
 * out because the Server Component `transcript-pane.tsx` needs to *call*
 * `shouldShowSourcesAffordance` directly -- and Next.js forbids calling any
 * export of a `"use client"` module from server code, even a pure function
 * with zero hooks/state (it can only be rendered or passed as a prop).
 * Mirrors the `lib/leads-presentation.ts` extraction for the same reason.
 */
import { useState } from "react";
import type { MessageSourcesResult } from "@/lib/conversations";
import {
  shouldShowSourcesAffordance,
  sourcesToggleLabel,
  sourceBodyText,
  sourceMetaLabel,
} from "@/app/(protected)/conversations/message-sources-presentation";

export { shouldShowSourcesAffordance, sourcesToggleLabel, sourceBodyText, sourceMetaLabel };

interface MessageSourcesProps {
  messageId: string;
  sourceCount: number;
  replyContent: string;
  fetchSourcesAction: (messageId: string) => Promise<MessageSourcesResult>;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; result: MessageSourcesResult };

export function MessageSources({ messageId, sourceCount, replyContent, fetchSourcesAction }: MessageSourcesProps) {
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<LoadState>({ status: "idle" });

  async function handleToggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && state.status === "idle") {
      setState({ status: "loading" });
      const result = await fetchSourcesAction(messageId);
      setState({ status: "loaded", result });
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={handleToggle}
        aria-expanded={expanded}
        className="w-fit text-[10.5px] font-semibold text-[#70716a] underline underline-offset-2"
      >
        {sourcesToggleLabel(sourceCount)}
      </button>

      {expanded ? (
        <div className="max-w-[520px] rounded-[10px] border border-[#e7e7e2] bg-[#fbfbf8] p-3 text-[12px]">
          {state.status === "loading" ? (
            <p role="status" className="text-[#96978e]">
              Loading sources…
            </p>
          ) : state.status === "loaded" && state.result.status === "error" ? (
            <p role="alert" className="text-[#c2452d]">
              {state.result.message}
            </p>
          ) : state.status === "loaded" && state.result.status === "ok" ? (
            <div className="flex flex-col gap-3">
              <div>
                <p className="mb-1 text-[10.5px] font-bold text-[#45463f]">Reply</p>
                <p className="text-[#191a17]">{replyContent}</p>
              </div>
              <div className="flex flex-col gap-2">
                {state.result.detail.sources.map((source) => (
                  <div key={source.chunkId} className="border-t border-[#e7e7e2] pt-2">
                    <p className="text-[10.5px] text-[#96978e]">{sourceMetaLabel(source)}</p>
                    <p className={source.resolved ? "text-[#191a17]" : "italic text-[#96978e]"}>
                      {sourceBodyText(source)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
