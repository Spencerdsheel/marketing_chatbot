/**
 * Conversations console (design id 4a, HANDOFF-SPEC.md §3), a new read-only
 * screen alongside `/leads`. `async` server component reading all state
 * (`?status=`, `?conversation=`, `?page=`) from `searchParams` and fetching
 * once per navigation -- no client state beyond the URL, mirroring
 * `leads/page.tsx`'s server-first pattern exactly.
 *
 * Layout: `admin-shell.tsx` (read-only, not modified -- see task scope) has
 * no separate "rail" concept for inner screens, only its one full 248px
 * sidebar used for every route. Per the task's explicit instruction, this
 * page therefore renders the 4a mock's list+transcript layout inside the
 * shell's normal content area rather than adding a second competing nav
 * rail -- i.e. a 2-pane (340px list + transcript) layout, not the mock's
 * literal 3-pane (icon rail + list + transcript), since the icon rail's job
 * (primary navigation) is already the shell's sidebar.
 *
 * Data shape and the mandated honest-UI deviations from the 4a mock are
 * documented in `lib/conversations.ts`, `presentation.ts`,
 * `conversation-list.tsx`, and `transcript-pane.tsx` -- summary:
 *  - LIVE/LEAD badges -> real ACTIVE/ENDED only (no live signal, no lead
 *    linkage field).
 *  - Filter pills -> real `status` values (active/ended), not LIVE/LEAD/
 *    ENDED.
 *  - "Source-attribution" line -> honest `intent`/`confidence` meta line,
 *    never labelled "source".
 *  - "Lead captured" chip -> omitted entirely (no lead-linkage field).
 *  - Takeover composer -> renders, permanently `disabled`, honest hint.
 */
import { requireAnyRole } from "@/lib/auth";
import {
  CONVERSATION_STATUSES,
  getConversationDetail,
  listConversations,
  type ConversationStatus,
} from "@/lib/conversations";
import { ConversationsFilter } from "@/app/(protected)/conversations/conversations-filter";
import { ConversationList } from "@/app/(protected)/conversations/conversation-list";
import { TranscriptPane } from "@/app/(protected)/conversations/transcript-pane";

interface ConversationsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function pageHref(page: number, status: ConversationStatus | undefined): string {
  const query = new URLSearchParams();
  if (page > 1) query.set("page", String(page));
  if (status) query.set("status", status);
  const qs = query.toString();
  return qs ? `/conversations?${qs}` : "/conversations";
}

export default async function ConversationsPage({ searchParams }: ConversationsPageProps) {
  await requireAnyRole("CLIENT_ADMIN", "CLIENT_AGENT");

  const params = await searchParams;
  const rawStatus = firstValue(params.status);
  const status =
    rawStatus && (CONVERSATION_STATUSES as readonly string[]).includes(rawStatus)
      ? (rawStatus as ConversationStatus)
      : undefined;
  const rawPage = Number.parseInt(firstValue(params.page) ?? "1", 10);
  const page = Number.isFinite(rawPage) && rawPage >= 1 ? rawPage : 1;
  const conversationId = firstValue(params.conversation);

  const currentParams = new URLSearchParams();
  if (page > 1) currentParams.set("page", String(page));
  if (status) currentParams.set("status", status);

  const listResult = await listConversations({ page, status });
  const detailResult = conversationId
    ? await getConversationDetail(conversationId)
    : null;

  return (
    <div className="flex flex-1 flex-col p-6 lg:p-8">
      <div
        className="flex flex-1 overflow-hidden rounded-[14px] border border-[#e7e7e2] bg-white"
        style={{ minHeight: "70vh" }}
      >
        <div className="flex w-full max-w-[340px] shrink-0 flex-col border-r border-[#e7e7e2]">
          <div className="flex flex-col gap-3 p-4.5 pb-3">
            <div className="flex items-center justify-between">
              <h1 className="text-[18px] font-bold text-[#191a17]">Conversations</h1>
              {listResult.status === "ok" ? (
                <span className="rounded-full bg-[#e4f222] px-2.5 py-[3px] text-[11px] font-bold text-[#191a17]">
                  {listResult.total}
                </span>
              ) : null}
            </div>
            <ConversationsFilter
              currentStatus={status}
              basePath="/conversations"
              statuses={CONVERSATION_STATUSES}
            />
          </div>

          {listResult.status === "error" ? (
            <p role="alert" className="m-4 rounded-[14px] border border-[#f6e3df] bg-[#fdf5f3] p-3 text-sm text-[#c2452d]">
              {listResult.message}
              {listResult.correlationId ? (
                <span className="mt-1 block text-xs opacity-80">
                  Correlation ID: {listResult.correlationId}
                </span>
              ) : null}
            </p>
          ) : (
            <>
              <ConversationList
                items={listResult.items}
                basePath="/conversations"
                currentParams={currentParams}
                selectedConversationId={conversationId}
              />
              {listResult.total > listResult.limit ? (
                <div className="flex items-center justify-between gap-2 border-t border-[#f0f0ea] px-4 py-3 text-[11.5px] text-[#70716a]">
                  <a
                    href={pageHref(page - 1, status)}
                    aria-disabled={listResult.offset === 0}
                    className={
                      listResult.offset === 0
                        ? "pointer-events-none opacity-40"
                        : "underline underline-offset-2"
                    }
                  >
                    Previous
                  </a>
                  <span>
                    {listResult.offset + 1}
                    {"–"}
                    {listResult.offset + listResult.items.length} of {listResult.total}
                  </span>
                  <a
                    href={pageHref(page + 1, status)}
                    aria-disabled={listResult.offset + listResult.limit >= listResult.total}
                    className={
                      listResult.offset + listResult.limit >= listResult.total
                        ? "pointer-events-none opacity-40"
                        : "underline underline-offset-2"
                    }
                  >
                    Next
                  </a>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="flex flex-1 flex-col">
          {!conversationId ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
              <p className="text-sm font-semibold text-[#45463f]">Select a conversation</p>
              <p className="max-w-sm text-xs text-[#96978e]">
                Choose a conversation from the list to view its full transcript.
              </p>
            </div>
          ) : detailResult === null ? null : detailResult.status === "error" ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
              <p role="alert" className="text-sm font-semibold text-[#c2452d]">
                {detailResult.message}
              </p>
              {detailResult.correlationId ? (
                <p className="text-xs text-[#96978e]">Correlation ID: {detailResult.correlationId}</p>
              ) : null}
            </div>
          ) : (
            <TranscriptPane conversation={detailResult.conversation} />
          )}
        </div>
      </div>
    </div>
  );
}
