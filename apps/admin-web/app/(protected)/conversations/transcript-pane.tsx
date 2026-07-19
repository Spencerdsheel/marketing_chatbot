/**
 * Transcript pane (HANDOFF-SPEC.md §3 "4a": "transcript pane (source-
 * attribution line under bot replies, centered 'Lead captured' event chip on
 * #eef7a8, take-over composer locked until takeover)"). Restyled from the
 * mock's raw markup (`Chatbot System Designs.dc.html#4a`, lines 59-86) to
 * real data with three mandated honest deviations from the mock:
 *
 *  1. "Source-attribution line" -> the real message schema has `intent` +
 *     `confidence` (float), NOT a source/citation/document field. This
 *     renders a "confidence: 0.94" style meta line under bot messages when
 *     `confidence` is present, and omits the line entirely otherwise. It is
 *     never labelled "source" and never fabricates a document name.
 *  2. "Lead captured" event chip -> omitted entirely. There is no
 *     lead-linkage field anywhere in `ConversationDetailResponse` (no
 *     `lead_id`), so rendering this chip would fabricate a connection the
 *     backend doesn't provide (CLAUDE.md §3, no silent fallbacks).
 *  3. Take-over composer -> renders visually per the mock but is always
 *     `disabled` (real HTML attribute, not just visual) with an honest
 *     permanent hint, since there is no live-bot-activity signal to detect
 *     and no admin-send-message endpoint to wire it to.
 */
import { formatDateTime, statusBadgeStyle } from "@/app/(protected)/conversations/presentation";
import type { ConversationDetail } from "@/lib/conversations";

function MessageBubble({
  role,
  content,
  intent,
  confidence,
  createdAt,
}: {
  role: string;
  content: string;
  intent: string | null;
  confidence: number | null;
  createdAt: string;
}) {
  const isVisitor = role === "user" || role === "visitor";
  const isBot = role === "assistant" || role === "bot";

  const bubble = isVisitor ? (
    <div
      className="max-w-[65%] self-end rounded-[14px_14px_4px_14px] bg-[#191a17] px-3.5 py-2.5 text-[13px] leading-relaxed text-white"
      title={formatDateTime(createdAt)}
    >
      {content}
    </div>
  ) : (
    <div className="flex max-w-[70%] items-end gap-2 self-start">
      {isBot ? (
        <span
          aria-hidden
          className="mb-0.5 size-[26px] shrink-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle at 35% 30%, #f4fa9a, #e4f222 70%, #b8c410)",
          }}
        />
      ) : null}
      <div
        className="rounded-[14px_14px_14px_4px] border border-[#e7e7e2] bg-white px-3.5 py-2.5 text-[13px] leading-relaxed text-[#191a17]"
        title={formatDateTime(createdAt)}
      >
        {content}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-1">
      {bubble}
      {isBot && confidence !== null ? (
        <span className="ml-9 text-[10.5px] text-[#96978e]">
          {intent ? `${intent} · ` : ""}confidence {confidence.toFixed(2)}
        </span>
      ) : null}
    </div>
  );
}

export function TranscriptPane({ conversation }: { conversation: ConversationDetail }) {
  const badge = statusBadgeStyle(conversation.status);

  return (
    <div className="flex flex-1 flex-col bg-[#f7f7f3]">
      <div className="flex items-center gap-3 border-b border-[#e7e7e2] bg-white px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-[14.5px] font-bold text-[#191a17]">
              {conversation.conversationId}
            </p>
            <span
              className="rounded-[5px] px-1.5 py-0.5 text-[9.5px] font-bold"
              style={{ background: badge.bg, color: badge.fg }}
            >
              {badge.label}
            </span>
          </div>
          <p className="truncate text-[11.5px] text-[#96978e]">
            {conversation.channel} · started {formatDateTime(conversation.startedAt)}
            {conversation.endedAt ? ` · ended ${formatDateTime(conversation.endedAt)}` : ""}
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-6">
        {conversation.summary ? (
          <p className="self-center rounded-full bg-[#ecece5] px-3 py-1 text-center text-[10.5px] text-[#96978e]">
            {conversation.summary}
          </p>
        ) : null}
        {conversation.messages.length === 0 ? (
          <p role="status" className="self-center text-[13px] text-[#96978e]">
            No messages in this conversation yet.
          </p>
        ) : (
          conversation.messages.map((message) => (
            <MessageBubble
              key={message.messageId}
              role={message.role}
              content={message.content}
              intent={message.intent}
              confidence={message.confidence}
              createdAt={message.createdAt}
            />
          ))
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-[#e7e7e2] bg-white px-6 py-3.5">
        <span className="rounded-full border border-dashed border-[#d5d5cb] px-3 py-1.5 text-[11px] whitespace-nowrap text-[#96978e]">
          Live takeover coming soon
        </span>
        <label htmlFor="takeover-composer" className="sr-only">
          Take over to type a reply
        </label>
        <input
          id="takeover-composer"
          type="text"
          disabled
          placeholder="Take over to type…"
          className="min-h-11 flex-1 rounded-full border border-[#e7e7e2] bg-[#f7f7f3] px-3.5 text-[13px] text-[#a8a99f] outline-none disabled:cursor-not-allowed"
        />
        <button
          type="button"
          disabled
          aria-label="Send (disabled -- live takeover not available yet)"
          className="grid size-11 shrink-0 place-items-center rounded-full bg-[#eef7a8] text-[14px] text-[#a8a99f] disabled:cursor-not-allowed"
        >
          <span aria-hidden>↑</span>
        </button>
      </div>
    </div>
  );
}
