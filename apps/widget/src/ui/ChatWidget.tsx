/**
 * Top-level chat component (S14.2 decision 1, scope item 2).
 *
 * Rendered by `entry.tsx` in place of S14.1's `<Placeholder>` on admission
 * success. Owns open/closed state, the in-memory message list, and the
 * in-memory `conversation_id` (decision 4). Renders the launcher
 * (open/close toggle) and, when open, the panel (header, message list,
 * input row). Orchestrates a send: optimistic user bubble -> typing
 * indicator -> sendTurn -> bot bubble (or error line, decision 7) -> store
 * the returned conversation_id.
 *
 * S14.5 adds: panel focus management (focus-in on open, a hand-rolled focus
 * trap while open, Escape-to-close, focus-restore to the launcher on close
 * — decision 1), `aria-labelledby` tying the dialog to its header, and the
 * opt-in TTS greeting + mute toggle (decision 5) triggered by the first
 * open gesture in this page session.
 *
 * S14.6 adds (decisions 1-7, scope item 3): a turn send is wrapped in
 * `withRetry` so a transient network/5xx/429 failure gets a **bounded**
 * auto-retry with a visible "retrying" status before an honest "offline" +
 * manual Retry (never a fabricated reply); a `401`/`403` triggers a
 * **bounded** single re-mint attempt (`mintVisitorSession`) rather than an
 * unbounded loop against the rate-limited admission endpoint; the
 * connection-status indicator (`ConnectionStatus`) renders in the header and
 * announces state *transitions* politely (not every retry tick); all
 * retry/reconnect timers are guarded by an `unmounted` ref so no fetch fires
 * after the panel/component is gone (the zombie-retry guard, decision 7).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { WidgetConfig } from "../config";
import { sendTurn, type TurnResult } from "../turn";
import { mintVisitorSession } from "../session";
import { withRetry } from "../retry";
import * as tts from "../tts";
import type { ChatMessage } from "./Bubble";
import { MessageList } from "./MessageList";
import { ConnectionStatus, type ConnectionState } from "./ConnectionStatus";

const LOG_PREFIX = "[chatbot-widget]";
const PANEL_HEADER_ID = "cw-panel-header";

/** Max attempts for the bounded auto-retry of a transient turn failure (decision 1/2). */
const TURN_RETRY_MAX_ATTEMPTS = 4;
/** Max attempts for the bounded expired-session re-mint (decision 5) — small
 * and capped since the re-mint itself hits the rate-limited /widget/session
 * endpoint; an unbounded loop here would storm it. */
const REMINT_MAX_ATTEMPTS = 2;

/** Small inline SVGs keep the embed self-contained without adding an icon package. */
function ChatGlyph({ name }: { name: "chat" | "close" | "sound" | "muted" | "send" }) {
  const common = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9 };
  if (name === "close") {
    return <svg aria-hidden="true" {...common}><path d="m6 6 12 12M18 6 6 18" /></svg>;
  }
  if (name === "send") {
    return <svg aria-hidden="true" {...common}><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>;
  }
  if (name === "sound" || name === "muted") {
    return (
      <svg aria-hidden="true" {...common}>
        <path d="M11 5 6 9H3v6h3l5 4Z" />
        {name === "sound" ? <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /> : <path d="m16 9 5 5m0-5-5 5" />}
      </svg>
    );
  }
  return <svg aria-hidden="true" {...common}><path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9.7 9.7 0 0 1-4.1-.9L3 21l1.9-4.1A8.4 8.4 0 0 1 3 11.5a8.5 8.5 0 0 1 18 0Z" /></svg>;
}

export interface ChatWidgetProps {
  config: WidgetConfig;
  expiresAt: string;
}

let messageIdCounter = 0;
function nextLocalId(): string {
  messageIdCounter += 1;
  return `local-${messageIdCounter}`;
}

/** Focusable-descendant query used by the hand-rolled focus trap (decision 1 —
 * no focus-trap library dependency, bundle-size rejection is locked). */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function getFocusableElements(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => !el.hasAttribute("disabled"),
  );
}

export function ChatWidget({ config, expiresAt }: ChatWidgetProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [pending, setPending] = useState(false);
  // In-memory only (decision 4) — never persisted, gone on reload.
  const conversationIdRef = useRef<string | null>(null);

  // S14.6: connection status + retry/reconnect state (decisions 1-7). All
  // in-memory (decision 7); nothing keyed by tenant_id.
  const [connectionState, setConnectionState] = useState<ConnectionState>({ kind: "online" });
  // Guards every retry/reconnect timer so no fetch fires once the component
  // is gone (decision 7 — the zombie-retry guard). Also gates against a
  // second concurrent send while a retry sequence is in flight.
  const unmountedRef = useRef(false);
  // Remembers the last failed send so the manual Retry control (shown once
  // auto-retry has stopped) can replay it without re-appending a duplicate
  // optimistic user bubble.
  const lastFailedSendRef = useRef<{ message: string; conversationId: string | null } | null>(null);

  useEffect(() => {
    return () => {
      unmountedRef.current = true;
    };
  }, []);

  const panelRef = useRef<HTMLDivElement | null>(null);
  const launcherRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // TTS: opt-in, in-memory-only mute preference (decision 5/6). Speaks only
  // once, on the first panel-open gesture in this page session.
  const [muted, setMuted] = useState(false);
  const hasGreetedRef = useRef(false);

  const toggleOpen = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      if (next && !hasGreetedRef.current) {
        // First open in this page session is the user gesture that
        // satisfies the browser autoplay policy (load-bearing constraint
        // 2) — never speak before this.
        hasGreetedRef.current = true;
        if (!muted) {
          tts.speakGreeting();
        }
      }
      if (!next) {
        // Closing (whether via toggle or Escape) stops any in-flight
        // greeting speech so it doesn't keep talking into a closed panel.
        tts.cancel();
      }
      return next;
    });
  }, [muted]);

  const toggleMuted = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      if (next) {
        tts.cancel();
      }
      return next;
    });
  }, []);

  // Focus-in on open (decision 1): move focus to the message input, the
  // first sensible target, once the panel mounts.
  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  // Focus-restore on close (decision 1): return focus to the launcher.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (!open && wasOpenRef.current) {
      launcherRef.current?.focus();
    }
    wasOpenRef.current = open;
  }, [open]);

  // Focus trap + Escape-to-close (decision 1): while open, Tab/Shift+Tab
  // cycle within the panel's focusable elements so keyboard focus can't
  // wander into the untrusted host page; Escape closes.
  const handlePanelKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        toggleOpen();
        return;
      }

      if (event.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusable = getFocusableElements(panel);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = panel.ownerDocument.activeElement;

      if (event.shiftKey) {
        if (active === first || !panel.contains(active)) {
          event.preventDefault();
          last?.focus();
        }
      } else {
        if (active === last || !panel.contains(active)) {
          event.preventDefault();
          first?.focus();
        }
      }
    },
    [toggleOpen],
  );

  /**
   * Bounded expired-session reconnect (decision 5): a 401/403 mid-
   * conversation gets ONE bounded re-mint attempt sequence (small capped
   * count, no backoff loop beyond that cap) — never a silent unbounded
   * re-auth, since the re-mint itself hits the rate-limited
   * `/widget/session` endpoint. Returns true if a fresh session was
   * minted, false if the cap was hit (caller shows the honest
   * "please reload" state).
   */
  const attemptSessionReconnect = useCallback(async (): Promise<boolean> => {
    setConnectionState({ kind: "reconnecting-session" });
    for (let attempt = 1; attempt <= REMINT_MAX_ATTEMPTS; attempt += 1) {
      if (unmountedRef.current) return false;
      const admission = await mintVisitorSession(config);
      if (admission.ok) return true;
      console.error(
        `${LOG_PREFIX} session re-mint attempt ${attempt}/${REMINT_MAX_ATTEMPTS} failed: ${admission.error.errorCode}`,
      );
    }
    return false;
  }, [config]);

  const runSend = useCallback(
    async (trimmed: string, conversationId: string | null) => {
      setPending(true);
      lastFailedSendRef.current = null;

      let attemptCount = 0;
      const result = await withRetry<TurnResult>(
        () => {
          attemptCount += 1;
          return sendTurn(config, { message: trimmed, conversationId });
        },
        {
          maxAttempts: TURN_RETRY_MAX_ATTEMPTS,
          shouldAbort: () => unmountedRef.current,
          onRetry: ({ error }) => {
            if (unmountedRef.current) return;
            if (error.errorCode === "RATE_LIMITED") {
              setConnectionState({ kind: "rate-limited", retryAfterSeconds: error.retryAfterSeconds ?? null });
            } else {
              setConnectionState({ kind: "retrying" });
            }
          },
        },
      );

      if (unmountedRef.current) return;
      setPending(false);

      if (!result.ok) {
        const { errorCode, correlationId, status } = result.error;
        console.error(
          `${LOG_PREFIX} turn failed: ${errorCode} (status=${status ?? "n/a"}, correlation_id=${correlationId ?? "n/a"}, attempts=${attemptCount}): ${result.error.message}`,
        );

        // Bounded expired-session reconnect (decision 5) — only for an
        // actual auth failure, not every retryable transport error.
        if (status === 401 || status === 403) {
          const reconnected = await attemptSessionReconnect();
          if (unmountedRef.current) return;
          if (reconnected) {
            setConnectionState({ kind: "online" });
            lastFailedSendRef.current = { message: trimmed, conversationId };
            setMessages((prev) => [
              ...prev,
              {
                id: nextLocalId(),
                role: "system-error",
                text: "Your session was reconnected. Please send your message again.",
              },
            ]);
            return;
          }
          setConnectionState({ kind: "session-expired" });
          setMessages((prev) => [
            ...prev,
            {
              id: nextLocalId(),
              role: "system-error",
              text: "Your session expired. Please reload the page to continue.",
            },
          ]);
          return;
        }

        // Auto-retry exhausted (or a non-retryable business error) — honest
        // failure, never a fabricated reply (decision 1/3 constraint 3).
        setConnectionState({ kind: "offline" });
        lastFailedSendRef.current = { message: trimmed, conversationId };
        setMessages((prev) => [
          ...prev,
          {
            id: nextLocalId(),
            role: "system-error",
            text: "Sorry — something went wrong. Please try again.",
          },
        ]);
        return;
      }

      setConnectionState({ kind: "online" });
      conversationIdRef.current = result.turn.conversationId;
      setMessages((prev) => [
        ...prev,
        {
          id: nextLocalId(),
          role: "bot",
          text: result.turn.reply,
          action: result.turn.action,
        },
      ]);
    },
    [config, attemptSessionReconnect],
  );

  const sendMessage = useCallback(async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || pending) return;

    const userMessage: ChatMessage = { id: nextLocalId(), role: "user", text: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    await runSend(trimmed, conversationIdRef.current);
  }, [pending, runSend]);

  const handleSend = useCallback(async () => {
    const message = inputValue;
    setInputValue("");
    await sendMessage(message);
  }, [inputValue, sendMessage]);

  const handleSuggestion = useCallback(async (message: string) => {
    await sendMessage(message);
  }, [sendMessage]);

  /** Manual Retry (decision 4/6): replay the last failed send without a new optimistic bubble. */
  const handleManualRetry = useCallback(async () => {
    const last = lastFailedSendRef.current;
    if (!last || pending) return;
    setConnectionState({ kind: "retrying" });
    await runSend(last.message, last.conversationId);
  }, [pending, runSend]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  return (
    <>
      {open && (
        <div
          className="cw-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby={PANEL_HEADER_ID}
          ref={panelRef}
          onKeyDown={handlePanelKeyDown}
        >
          <div className="cw-panel-header">
            <span className="cw-assistant-mark" aria-hidden="true" />
            <span className="cw-panel-title">
              <span id={PANEL_HEADER_ID}>Assistant</span>
              <span className="cw-panel-presence">Usually replies instantly</span>
            </span>
            <span className="cw-header-actions">
              <button
                type="button"
                className="cw-mute-toggle"
                onClick={toggleMuted}
                aria-pressed={muted}
                aria-label={muted ? "Turn greeting sound on" : "Turn greeting sound off"}
              >
                <ChatGlyph name={muted ? "muted" : "sound"} />
                <span className="cw-mute-toggle-label" aria-hidden="true">
                  {muted ? "Off" : "On"}
                </span>
              </button>
              <button type="button" className="cw-close-button" onClick={toggleOpen} aria-label="Close chat">
                <ChatGlyph name="close" />
              </button>
            </span>
          </div>
          <ConnectionStatus state={connectionState} onRetry={() => void handleManualRetry()} />
          <MessageList messages={messages} pending={pending} config={config} onSuggestion={(message) => void handleSuggestion(message)} />
          <div className="cw-input-row">
            <input
              ref={inputRef}
              type="text"
              className="cw-input"
              placeholder="Type a message…"
              value={inputValue}
              disabled={pending}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label="Message"
            />
            <button
              type="button"
              className="cw-send-button"
              disabled={pending || inputValue.trim().length === 0}
              onClick={() => void handleSend()}
              aria-label="Send message"
            >
              <ChatGlyph name="send" />
            </button>
          </div>
        </div>
      )}
      <button
        type="button"
        className="cw-placeholder cw-launcher"
        ref={launcherRef}
        onClick={toggleOpen}
        aria-label={open ? "Close chat" : "Open chat"}
        aria-expanded={open}
        data-expires-at={expiresAt}
      >
        <ChatGlyph name={open ? "close" : "chat"} />
        <span className="cw-launcher-label">{open ? "Close" : "Chat"}</span>
      </button>
      {!open && (
        <div className="cw-teaser" role="status">
          <span>Questions? I can help.</span>
          <span className="cw-teaser-tail" aria-hidden="true" />
        </div>
      )}
    </>
  );
}
