/**
 * Ink & Citron visual system for the Shadow DOM widget. It intentionally
 * lives in a TS string so the production embed remains one self-contained
 * file and none of these rules can leak into a client's host page.
 */
export const widgetCss = `
:host {
  all: initial;
  --cw-ink: #191a17;
  --cw-citron: #e4f222;
  --cw-paper: #ffffff;
  --cw-cool-paper: #f7f7f3;
  --cw-line: #e7e7e2;
  --cw-muted: #70716a;
  --cw-dim: #96978e;
  --cw-success: #286a39;
  --cw-warning-bg: #fff9ec;
  --cw-warning-line: #f0e2bd;
  --cw-warning-ink: #6a4e00;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--cw-ink);
  line-height: 1.45;
}

*, *::before, *::after { box-sizing: border-box; }
button, input { font: inherit; }
button { -webkit-tap-highlight-color: transparent; touch-action: manipulation; }

.cw-placeholder {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2147483000;
  min-width: 56px;
  min-height: 56px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 18px;
  border: 1px solid var(--cw-ink);
  border-radius: 999px;
  background: var(--cw-ink);
  color: var(--cw-citron);
  box-shadow: 0 10px 26px rgba(25, 26, 23, 0.28);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.01em;
  cursor: pointer;
  transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease;
}
.cw-placeholder:hover { background: #30312c; box-shadow: 0 13px 30px rgba(25, 26, 23, 0.34); }
.cw-placeholder:active { transform: scale(0.97); }
.cw-placeholder:focus-visible, .cw-input:focus-visible, .cw-suggestion:focus-visible,
.cw-mute-toggle:focus-visible, .cw-close-button:focus-visible, .cw-send-button:focus-visible,
.cw-lead-input:focus-visible, .cw-lead-checkbox:focus-visible, .cw-lead-submit:focus-visible,
.cw-sched-slot:focus-visible, .cw-sched-checkbox:focus-visible, .cw-sched-confirm-button:focus-visible,
.cw-sched-back-button:focus-visible, .cw-sched-retry:focus-visible, .cw-status-retry:focus-visible {
  outline: 3px solid var(--cw-citron);
  outline-offset: 2px;
}

.cw-teaser {
  position: fixed;
  right: 88px;
  bottom: 29px;
  z-index: 2147482999;
  max-width: calc(100vw - 172px);
  padding: 10px 14px;
  border: 1px solid var(--cw-line);
  border-radius: 12px;
  background: var(--cw-paper);
  color: #45463f;
  box-shadow: 0 7px 20px rgba(25, 26, 23, 0.13);
  font-size: 12px;
  white-space: nowrap;
}
.cw-teaser-tail { position: absolute; right: -5px; bottom: 10px; width: 10px; height: 10px; background: var(--cw-paper); border-top: 1px solid var(--cw-line); border-right: 1px solid var(--cw-line); transform: rotate(45deg); }

.cw-diagnostic { position: fixed; right: 20px; bottom: 88px; z-index: 2147483000; max-width: 320px; padding: 12px 14px; border: 1px solid #b23a32; border-radius: 10px; background: #fff1ef; color: #79221d; font-size: 12px; box-shadow: 0 8px 22px rgba(25, 26, 23, 0.18); }

.cw-panel {
  position: fixed;
  right: 20px;
  bottom: 88px;
  z-index: 2147483000;
  width: min(350px, calc(100vw - 32px));
  height: min(520px, calc(100dvh - 116px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(25, 26, 23, 0.12);
  border-radius: 18px;
  background: var(--cw-paper);
  box-shadow: 0 18px 48px rgba(25, 26, 23, 0.27);
  animation: cw-panel-in 220ms cubic-bezier(.16, 1, .3, 1);
}
.cw-panel-header { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; min-height: 64px; padding: 10px 12px 10px 16px; background: var(--cw-ink); color: var(--cw-paper); }
.cw-assistant-mark, .cw-welcome-orb { display: inline-block; flex: 0 0 auto; border-radius: 999px; background: radial-gradient(circle at 35% 30%, #f7ffaf 0, var(--cw-citron) 58%, #b6c319 100%); }
.cw-assistant-mark { width: 30px; height: 30px; box-shadow: inset 0 0 0 1px rgba(255,255,255,.15); }
.cw-panel-title { display: flex; flex: 1 1 auto; min-width: 0; flex-direction: column; gap: 1px; font-size: 13.5px; font-weight: 750; letter-spacing: -0.01em; }
.cw-panel-presence { color: #c7d856; font-size: 10.5px; font-weight: 500; }
.cw-header-actions { display: flex; align-items: center; gap: 2px; }
.cw-mute-toggle, .cw-close-button { width: 44px; height: 44px; display: inline-flex; align-items: center; justify-content: center; border: 0; border-radius: 999px; background: transparent; color: #e5e6df; cursor: pointer; transition: background 160ms ease, color 160ms ease; }
.cw-mute-toggle:hover, .cw-close-button:hover { background: rgba(255,255,255,.12); color: var(--cw-citron); }
.cw-mute-toggle svg, .cw-close-button svg, .cw-send-button svg, .cw-launcher svg { display: block; }

.cw-status { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-bottom: 1px solid var(--cw-warning-line); background: var(--cw-warning-bg); color: var(--cw-warning-ink); font-size: 11px; }
.cw-status:empty { display: none; }
.cw-status-text { flex: 1 1 auto; }
.cw-status-retry { min-height: 44px; padding: 7px 12px; border: 1px solid currentColor; border-radius: 999px; background: transparent; color: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }

.cw-message-list { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; padding: 14px; background: var(--cw-cool-paper); scrollbar-color: #c6c7bd transparent; }
.cw-welcome { display: flex; min-height: 100%; flex-direction: column; align-items: center; justify-content: center; padding: 18px 5px; text-align: center; }
.cw-welcome-orb { width: 58px; height: 58px; margin-bottom: 14px; box-shadow: 0 8px 20px rgba(184, 196, 16, .22); }
.cw-welcome h2 { margin: 0; color: var(--cw-ink); font-size: 17px; line-height: 1.25; letter-spacing: -0.025em; }
.cw-welcome p { max-width: 270px; margin: 7px 0 16px; color: var(--cw-muted); font-size: 12.5px; line-height: 1.5; }
.cw-suggestions { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.cw-suggestion { width: 100%; min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; border: 1px solid var(--cw-line); border-radius: 10px; background: var(--cw-paper); color: #45463f; font-size: 12.5px; text-align: left; cursor: pointer; transition: border-color 160ms ease, transform 160ms ease, background 160ms ease; }
.cw-suggestion:hover { border-color: #c5c6bd; background: #fbfbf8; }
.cw-suggestion:active { transform: scale(.985); }

.cw-bubble-row { display: flex; width: 100%; }
.cw-bubble-row-user { justify-content: flex-end; }
.cw-bubble-row-bot { justify-content: flex-start; }
.cw-bubble { max-width: 85%; padding: 10px 13px; border-radius: 14px; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.cw-bubble-user { border-bottom-right-radius: 4px; background: var(--cw-ink); color: var(--cw-paper); }
.cw-bubble-bot { border: 1px solid var(--cw-line); border-bottom-left-radius: 4px; background: var(--cw-paper); color: var(--cw-ink); }
.cw-md-paragraph { margin: 0; }
.cw-md-paragraph + .cw-md-paragraph { margin-top: 8px; }
.cw-bubble a { color: #38410b; font-weight: 650; text-decoration: underline; }
.cw-bubble code { padding: 1px 4px; border-radius: 4px; background: #ecece5; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.cw-typing { gap: 5px; padding: 14px; }
.cw-typing-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--cw-muted); }
.cw-line { align-self: center; padding: 7px 10px; border-radius: 8px; font-size: 12px; text-align: center; }
.cw-line-error, .cw-lead-error, .cw-sched-error { border: 1px solid #d99b95; background: #fff1ef; color: #79221d; }

.cw-input-row { flex: 0 0 auto; display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--cw-line); background: var(--cw-paper); }
.cw-input { flex: 1 1 auto; min-width: 0; min-height: 44px; padding: 10px 14px; border: 1px solid var(--cw-line); border-radius: 999px; background: var(--cw-paper); color: var(--cw-ink); font-size: 13px; }
.cw-input::placeholder { color: var(--cw-dim); }
.cw-input:disabled { background: var(--cw-cool-paper); color: var(--cw-dim); }
.cw-send-button { width: 44px; height: 44px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #c0cb1d; border-radius: 999px; background: var(--cw-citron); color: var(--cw-ink); cursor: pointer; transition: transform 160ms ease, background 160ms ease; }
.cw-send-button:hover:not(:disabled) { background: #f0ff45; }
.cw-send-button:active:not(:disabled) { transform: scale(.95); }
.cw-send-button:disabled { border-color: #e5e6df; background: #eef0d5; color: #a1a29a; cursor: not-allowed; }

.cw-lead-form, .cw-sched { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--cw-line); }
.cw-lead-field { display: flex; flex-direction: column; gap: 4px; }
.cw-lead-label, .cw-sched-list-label { color: #5a5b54; font-size: 11px; font-weight: 700; }
.cw-lead-input { min-height: 44px; padding: 8px 10px; border: 1px solid var(--cw-line); border-radius: 9px; background: var(--cw-paper); color: var(--cw-ink); font-size: 13px; }
.cw-lead-input:disabled { background: var(--cw-cool-paper); color: var(--cw-dim); }
.cw-lead-consent-row, .cw-sched-consent-row { display: flex; align-items: flex-start; gap: 8px; }
.cw-lead-checkbox, .cw-sched-checkbox { width: 18px; height: 18px; flex: 0 0 auto; margin: 1px 0 0; accent-color: var(--cw-citron); }
.cw-lead-consent-label, .cw-sched-consent-label { color: #5a5b54; font-size: 11px; line-height: 1.45; }
.cw-lead-error, .cw-sched-error { padding: 7px 8px; border-radius: 7px; font-size: 11px; }
.cw-lead-submit, .cw-sched-confirm-button, .cw-sched-retry { min-height: 44px; align-self: flex-start; padding: 9px 15px; border: 1px solid var(--cw-ink); border-radius: 999px; background: var(--cw-ink); color: var(--cw-citron); font-size: 12px; font-weight: 750; cursor: pointer; }
.cw-lead-submit:hover:not(:disabled), .cw-sched-confirm-button:hover:not(:disabled), .cw-sched-retry:hover { background: #30312c; }
.cw-lead-submit:disabled, .cw-sched-confirm-button:disabled { border-color: #e5e6df; background: #e5e6df; color: #96978e; cursor: not-allowed; }
.cw-lead-confirmation, .cw-sched-confirmation { margin-top: 10px; padding: 10px 0 0; border-top: 1px dashed var(--cw-line); color: var(--cw-success); font-size: 12px; font-weight: 650; }

.cw-sched { color: var(--cw-ink); font-size: 12px; }
.cw-sched-list { display: flex; flex-direction: column; gap: 7px; margin: 0; padding: 0; list-style: none; }
.cw-sched-slot { width: 100%; min-height: 44px; padding: 8px 10px; border: 1px solid var(--cw-line); border-radius: 9px; background: var(--cw-paper); color: var(--cw-ink); font-size: 12.5px; text-align: left; cursor: pointer; }
.cw-sched-slot:hover { border-color: var(--cw-ink); background: #fafaef; }
.cw-sched-empty { color: #5a5b54; }
.cw-sched-confirm-heading { color: var(--cw-ink); font-size: 13px; font-weight: 700; }
.cw-lead-confirmation:focus-visible, .cw-sched-confirmation:focus-visible, .cw-sched-confirm-heading:focus-visible { outline: 3px solid var(--cw-citron); outline-offset: 3px; }
.cw-sched-confirm-actions { display: flex; gap: 8px; }
.cw-sched-back-button { min-height: 44px; padding: 9px 15px; border: 1px solid var(--cw-line); border-radius: 999px; background: var(--cw-paper); color: #45463f; font-size: 12px; font-weight: 700; cursor: pointer; }
.cw-sched-back-button:hover:not(:disabled) { background: var(--cw-cool-paper); }
.cw-sched-back-button:disabled { color: var(--cw-dim); cursor: not-allowed; }

@media (prefers-reduced-motion: no-preference) {
  .cw-typing-dot { animation: cw-typing-bounce 1.2s infinite ease-in-out; }
  .cw-typing-dot:nth-child(2) { animation-delay: .15s; }
  .cw-typing-dot:nth-child(3) { animation-delay: .3s; }
}
@keyframes cw-typing-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: .55; } 30% { transform: translateY(-4px); opacity: 1; } }
@keyframes cw-panel-in { from { transform: translateY(8px) scale(.98); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .cw-panel, .cw-placeholder, .cw-suggestion, .cw-send-button { animation: none; transition: none; } }
@media (max-width: 480px) {
  .cw-panel { right: 8px; bottom: 76px; width: calc(100vw - 16px); height: min(560px, calc(100dvh - 88px)); border-radius: 16px; }
  .cw-placeholder { right: 12px; bottom: 12px; }
  .cw-teaser { right: 80px; bottom: 20px; max-width: calc(100vw - 160px); overflow: hidden; text-overflow: ellipsis; }
}
`;
