/**
 * Boot orchestration tests (S14.6 scope item 4/8).
 *
 * `entry.tsx` is the widget's one top-level-side-effect module: importing
 * it calls `boot()` immediately. To test the S14.6 bounded-retry addition
 * without a real network, this suite mocks `./config`, `./mount`, and
 * `./session`, then dynamically re-imports `./entry` under fake timers so
 * `withRetry`'s default `setTimeout`-based backoff can be flushed
 * deterministically (no real waiting).
 */
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WidgetConfig } from "./config";
import type { AdmissionResult } from "./session";

const renderMock = vi.fn();
const loadConfigMock = vi.fn<() => { ok: true; config: WidgetConfig }>();
const mountWidgetMock = vi.fn<(mountSelector: string | null) => { reactRoot: { render: typeof renderMock } }>();
const mintVisitorSessionMock = vi.fn<(config: WidgetConfig) => Promise<AdmissionResult>>();

vi.mock("./config", () => ({
  loadConfig: () => loadConfigMock(),
}));

vi.mock("./mount", () => ({
  mountWidget: (mountSelector: string | null) => mountWidgetMock(mountSelector),
}));

vi.mock("./session", () => ({
  mintVisitorSession: (config: WidgetConfig) => mintVisitorSessionMock(config),
}));

// entry.tsx renders <ChatWidget>/<DiagnosticStrip> via reactRoot.render — stub
// both leaf components out so this suite only asserts on the boot sequence
// (retry count, honest hard-stop, final render call), not their internals.
vi.mock("./ui/ChatWidget", () => ({
  ChatWidget: () => null,
}));
vi.mock("./ui/DiagnosticStrip", () => ({
  DiagnosticStrip: () => null,
}));

const baseConfig: WidgetConfig = {
  clientKey: "pk_test_123",
  apiBase: "http://localhost:8000",
  mountSelector: null,
  debug: true,
};

// Not a real credential — a short fixture id used only to distinguish
// "session A" from "session B" in the assertions below.
const FIXTURE_SESSION_A = "fixture-a";
const FIXTURE_SESSION_B = "fixture-b";

async function flushRetries(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20000);
  });
}

describe("entry.tsx boot()", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    loadConfigMock.mockReset();
    mountWidgetMock.mockReset();
    mintVisitorSessionMock.mockReset();
    renderMock.mockReset();
    mountWidgetMock.mockReturnValue({ reactRoot: { render: renderMock } });
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("a transient boot admission network failure is retried bounded then honestly hard-stops (debug strip on cap-hit, no ChatWidget render)", async () => {
    loadConfigMock.mockReturnValue({ ok: true, config: baseConfig });
    mintVisitorSessionMock.mockResolvedValue({
      ok: false,
      error: {
        type: "ADMISSION_ERROR",
        errorCode: "NETWORK_ERROR",
        message: "Network request failed.",
        correlationId: null,
        status: null,
        retryAfterSeconds: null,
      },
    });

    await act(async () => {
      await import("./entry");
    });
    await flushRetries();

    // Bounded: the default withRetry cap (4) — not unbounded, not a tight loop.
    expect(mintVisitorSessionMock.mock.calls.length).toBe(4);
    // Honest hard-stop: debug is on, so the diagnostic strip renders — never ChatWidget.
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it("a non-retryable admission error (INVALID_CLIENT_KEY) is NOT retried — exactly one attempt", async () => {
    loadConfigMock.mockReturnValue({ ok: true, config: baseConfig });
    mintVisitorSessionMock.mockResolvedValue({
      ok: false,
      error: {
        type: "ADMISSION_ERROR",
        errorCode: "INVALID_CLIENT_KEY",
        message: "Unknown client key.",
        correlationId: "corr-1",
        status: 422,
        retryAfterSeconds: null,
      },
    });

    await act(async () => {
      await import("./entry");
    });
    await flushRetries();

    expect(mintVisitorSessionMock).toHaveBeenCalledTimes(1);
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it("a successful mint (first attempt) renders ChatWidget with no retry", async () => {
    loadConfigMock.mockReturnValue({ ok: true, config: baseConfig });
    mintVisitorSessionMock.mockResolvedValue({
      ok: true,
      session: { visitorToken: FIXTURE_SESSION_A, expiresAt: "2026-07-16T13:00:00Z" },
    });

    await act(async () => {
      await import("./entry");
    });
    await flushRetries();

    expect(mintVisitorSessionMock).toHaveBeenCalledTimes(1);
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it("a transient failure that succeeds on a later bounded attempt renders ChatWidget (not the diagnostic strip)", async () => {
    loadConfigMock.mockReturnValue({ ok: true, config: baseConfig });
    mintVisitorSessionMock
      .mockResolvedValueOnce({
        ok: false,
        error: {
          type: "ADMISSION_ERROR",
          errorCode: "NETWORK_ERROR",
          message: "Network request failed.",
          correlationId: null,
          status: null,
          retryAfterSeconds: null,
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        session: { visitorToken: FIXTURE_SESSION_B, expiresAt: "2026-07-16T13:00:00Z" },
      });

    await act(async () => {
      await import("./entry");
    });
    await flushRetries();

    expect(mintVisitorSessionMock).toHaveBeenCalledTimes(2);
    expect(renderMock).toHaveBeenCalledTimes(1);
  });
});
