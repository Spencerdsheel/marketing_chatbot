/**
 * Client-safe presentation layer for the grounding spot-check affordance
 * (SR-2). Pure, non-hook helper functions only -- no `"use client"`, no
 * `"server-only"` -- so both the Server Component `transcript-pane.tsx` and
 * the Client Component `message-sources.tsx` can import them directly.
 *
 * Mirrors the `lib/leads-presentation.ts` pattern: a Server Component may
 * only *render* or *prop-pass* an export from a `"use client"` module, never
 * *call* it directly. `shouldShowSourcesAffordance` is called directly (as a
 * plain function, to decide whether to render `<MessageSources>`) from
 * `transcript-pane.tsx`'s `MessageBubble`, so it -- and its sibling pure
 * helpers -- must live outside `message-sources.tsx`.
 *
 * `message-sources.tsx` re-exports these so existing importers (its own test
 * suite) keep working unchanged -- this file is the single source of truth,
 * `message-sources.tsx` just forwards them.
 */
import type { MessageSourceItem } from "@/lib/conversations";

const UNRESOLVED_SOURCE_LABEL = "source no longer in the knowledge base";

/** The "View sources" affordance renders ONLY for a bot message with
 * `sourceCount > 0` -- never for a visitor/user message, and never for a
 * bot message with zero cited sources (chit-chat/escalate-with-no-answer).
 * Pure, exported for unit testing (this repo has no DOM/React-testing-
 * library dependency wired up -- mirrors `schedule-polling.ts`'s
 * pure-driver-extraction pattern). */
export function shouldShowSourcesAffordance(role: string, sourceCount: number): boolean {
  const isBot = role === "assistant" || role === "bot";
  return isBot && sourceCount > 0;
}

/** Toggle label -- "View sources (N)". */
export function sourcesToggleLabel(sourceCount: number): string {
  return `View sources (${sourceCount})`;
}

/** A resolved source's body text is its real chunk content; an unresolved
 * one gets the honest "no longer in the knowledge base" line -- never blank,
 * never placeholder/fabricated text (no silent fallback, CLAUDE.md §3). */
export function sourceBodyText(source: Pick<MessageSourceItem, "resolved" | "content">): string {
  return source.resolved && source.content !== null ? source.content : UNRESOLVED_SOURCE_LABEL;
}

/** Display label for a single source's meta line: "doc_id · chunk_id[ ·
 * score X.XX]" -- score is echoed as-is (no verdict/threshold coloring, no
 * groundedness scoring -- decision 6). */
export function sourceMetaLabel(source: Pick<MessageSourceItem, "docId" | "chunkId" | "score">): string {
  const base = `${source.docId} · ${source.chunkId}`;
  return source.score !== null ? `${base} · score ${source.score.toFixed(2)}` : base;
}
