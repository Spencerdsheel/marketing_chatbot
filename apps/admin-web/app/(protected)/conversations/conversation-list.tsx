/**
 * 340px conversation list (HANDOFF-SPEC.md §3 "4a": "340px list (filter
 * pills, LIVE/LEAD/ENDED badges, active row = #ecece5 + 3px citron left
 * bar)"). Restyled from the mock's raw markup (`Chatbot System Designs.dc.
 * html#4a`, lines 29-58) to real data: initials avatar, name/visitor label,
 * approximate relative time, `summary` as the preview line, and the honest
 * ACTIVE/ENDED status badge (see `presentation.ts` for why there's no LIVE/
 * LEAD badge).
 *
 * Each row is a `<Link>` (not a div+onClick), matching `leads-table.tsx`'s
 * progressive-enhancement pattern -- keyboard/middle-click/right-click
 * navigable, works with JS disabled. Selected-conversation state lives in
 * the URL (`?conversation=<id>`), mirroring `?lead=<id>`.
 */
import Link from "next/link";
import type { ConversationListItem } from "@/lib/conversations";
import { initialsFromVisitor, lastActivityAt, relativeTime, statusBadgeStyle, visitorLabel } from "@/app/(protected)/conversations/presentation";

function conversationHref(
  basePath: string,
  currentParams: URLSearchParams,
  conversationId: string
): string {
  const params = new URLSearchParams(currentParams);
  params.set("conversation", conversationId);
  return `${basePath}?${params.toString()}`;
}

export function ConversationList({
  items,
  basePath,
  currentParams,
  selectedConversationId,
}: {
  items: ConversationListItem[];
  basePath: string;
  currentParams: URLSearchParams;
  selectedConversationId?: string;
}) {
  if (items.length === 0) {
    return (
      <p role="status" className="p-5 text-[13px] text-[#96978e]">
        No conversations yet -- conversations started by your chatbot will appear here.
      </p>
    );
  }

  return (
    <ul className="flex flex-1 flex-col overflow-y-auto" aria-label="Conversations">
      {items.map((item) => {
        const selected = item.conversationId === selectedConversationId;
        const badge = statusBadgeStyle(item.status);
        const label = visitorLabel(item.visitorId);
        return (
          <li
            key={item.conversationId}
            className="border-t border-[#f0f0ea] first:border-t-0"
            style={
              selected
                ? { background: "#ecece5", borderLeft: "3px solid #e4f222" }
                : { borderLeft: "3px solid transparent" }
            }
          >
            <Link
              href={conversationHref(basePath, currentParams, item.conversationId)}
              scroll={false}
              aria-current={selected ? "true" : undefined}
              className="flex min-h-[44px] gap-2.5 px-4 py-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#191a17]"
            >
              <span className="grid size-[34px] shrink-0 place-items-center rounded-full bg-[#dcdcd2] text-[11px] font-bold text-[#5a5b54]">
                {initialsFromVisitor(item.visitorId)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-bold text-[#191a17]">{label}</span>
                  <span className="shrink-0 text-[10.5px] text-[#96978e]">
                    {relativeTime(lastActivityAt(item))}
                  </span>
                </span>
                <span className="block truncate text-[11.5px] text-[#5a5b54]">
                  {item.summary ?? `${item.messageCount} message${item.messageCount === 1 ? "" : "s"}`}
                </span>
                <span className="mt-1 flex gap-1.5">
                  <span
                    className="rounded-[5px] px-1.5 py-0.5 text-[9.5px] font-bold"
                    style={{ background: badge.bg, color: badge.fg }}
                  >
                    {badge.label}
                  </span>
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
