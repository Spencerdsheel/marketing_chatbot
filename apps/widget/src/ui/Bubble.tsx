/**
 * Chat bubble rendering (S14.2 scope item 3, S14.3 decision 1, S14.4
 * decision 1): user/bot/system bubbles, plus the typing/thinking indicator
 * as a distinct list item. A bot message carrying `action="lead_form"`
 * renders the real consent-gated `<LeadForm>` (S14.3); `action="schedule_cta"`
 * renders the real consent-gated `<ScheduleCta>` (S14.4). `ActionStub` has
 * no live callers after S14.4 and has been removed.
 */
import { Markdown } from "./Markdown";
import { LeadForm } from "./LeadForm";
import { ScheduleCta } from "./ScheduleCta";
import type { WidgetConfig } from "../config";

export interface ChatMessage {
  id: string;
  role: "user" | "bot" | "system-error";
  text: string;
  /** Only ever set on a bot message (decision 5). */
  action?: "lead_form" | "schedule_cta" | null;
}

export function Bubble({ message, config }: { message: ChatMessage; config: WidgetConfig }) {
  if (message.role === "system-error") {
    return (
      <div className="cw-line cw-line-error" role="alert">
        {message.text}
      </div>
    );
  }

  const isUser = message.role === "user";
  return (
    <div className={`cw-bubble-row ${isUser ? "cw-bubble-row-user" : "cw-bubble-row-bot"}`}>
      <div className={`cw-bubble ${isUser ? "cw-bubble-user" : "cw-bubble-bot"}`}>
        {isUser ? message.text : <Markdown text={message.text} />}
        {!isUser && message.action === "lead_form" ? <LeadForm config={config} /> : null}
        {!isUser && message.action === "schedule_cta" ? <ScheduleCta config={config} /> : null}
      </div>
    </div>
  );
}

/** The typing/thinking indicator, shown as a distinct list item while a turn is in flight. */
export function TypingIndicator() {
  return (
    <div className="cw-bubble-row cw-bubble-row-bot" aria-live="off">
      <div className="cw-bubble cw-bubble-bot cw-typing" role="status" aria-label="Bot is typing">
        <span className="cw-typing-dot" />
        <span className="cw-typing-dot" />
        <span className="cw-typing-dot" />
      </div>
    </div>
  );
}
