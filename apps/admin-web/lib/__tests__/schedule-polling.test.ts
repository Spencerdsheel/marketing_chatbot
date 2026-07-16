import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { schedulePolling } from "@/lib/knowledge-constants";

/**
 * Fake-timer coverage for the knowledge-upload status panel's poll loop
 * (S13.3 decision 4): proves polling actually stops on a terminal state and
 * respects the poll cap, per the sprint's "Definition of Done" requirement
 * for an explicit test of this behavior. `schedulePolling` is the pure
 * driver extracted from `upload-form.tsx`'s `StatusPanel` so this is
 * testable without a DOM/React-testing-library dependency (none is wired up
 * in this repo).
 */
describe("schedulePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls immediately, then on the interval, and stops once isTerminal is true", async () => {
    const results = ["queued", "running", "succeeded"];
    let callIndex = 0;
    const pollOnce = vi.fn(async () => results[Math.min(callIndex++, results.length - 1)]);
    const onResult = vi.fn();

    schedulePolling<string>({
      pollOnce,
      isTerminal: (r) => r === "succeeded",
      onResult,
      intervalMs: 2500,
      maxPolls: 120,
    });

    // Immediate first poll (microtask-scheduled).
    await vi.advanceTimersByTimeAsync(0);
    expect(pollOnce).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenNthCalledWith(1, "queued", 1);

    await vi.advanceTimersByTimeAsync(2500);
    expect(pollOnce).toHaveBeenCalledTimes(2);
    expect(onResult).toHaveBeenNthCalledWith(2, "running", 2);

    await vi.advanceTimersByTimeAsync(2500);
    expect(pollOnce).toHaveBeenCalledTimes(3);
    expect(onResult).toHaveBeenNthCalledWith(3, "succeeded", 3);

    // Terminal state reached -- further interval ticks must NOT call pollOnce
    // again (the driver clears its own interval).
    await vi.advanceTimersByTimeAsync(2500 * 5);
    expect(pollOnce).toHaveBeenCalledTimes(3);
  });

  it("stops after maxPolls attempts without a terminal result, firing onCapped once", async () => {
    const pollOnce = vi.fn(async () => "queued");
    const onCapped = vi.fn();

    schedulePolling<string>({
      pollOnce,
      isTerminal: () => false,
      onResult: () => {},
      onCapped,
      intervalMs: 100,
      maxPolls: 5,
    });

    // Immediate poll (#1) + 4 interval ticks (#2-#5) = 5 total.
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100 * 10);

    expect(pollOnce).toHaveBeenCalledTimes(5);
    expect(onCapped).toHaveBeenCalledTimes(1);

    // No further polls after the cap.
    await vi.advanceTimersByTimeAsync(100 * 10);
    expect(pollOnce).toHaveBeenCalledTimes(5);
  });

  it("stop() from the returned handle halts polling immediately (React unmount cleanup)", async () => {
    const pollOnce = vi.fn(async () => "queued");

    const stop = schedulePolling<string>({
      pollOnce,
      isTerminal: () => false,
      onResult: () => {},
      intervalMs: 100,
      maxPolls: 120,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(pollOnce).toHaveBeenCalledTimes(1);

    stop();

    await vi.advanceTimersByTimeAsync(100 * 20);
    expect(pollOnce).toHaveBeenCalledTimes(1);
  });
});
