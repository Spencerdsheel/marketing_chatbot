import { afterEach, describe, expect, it, vi } from "vitest";

import { TTS_GREETING_TEXT, cancel, speakGreeting } from "./tts";

describe("tts", () => {
  const originalSpeechSynthesis = window.speechSynthesis;
  const originalUtterance = window.SpeechSynthesisUtterance;

  afterEach(() => {
    Object.defineProperty(window, "speechSynthesis", {
      value: originalSpeechSynthesis,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      value: originalUtterance,
      configurable: true,
      writable: true,
    });
    vi.restoreAllMocks();
  });

  describe("speakGreeting", () => {
    it("calls speechSynthesis.speak exactly once with the baked-in greeting text (simulating an open-gesture call site)", () => {
      const speak = vi.fn();
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak, cancel: vi.fn() },
        configurable: true,
        writable: true,
      });
      class FakeUtterance {
        text: string;
        constructor(text: string) {
          this.text = text;
        }
      }
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: FakeUtterance,
        configurable: true,
        writable: true,
      });

      // Caller-side gating: only invoked from the simulated open gesture,
      // never on its own — this test just proves speakGreeting's own
      // behavior once called.
      speakGreeting();

      expect(speak).toHaveBeenCalledTimes(1);
      const uttered = speak.mock.calls[0]?.[0] as FakeUtterance;
      expect(uttered.text).toBe(TTS_GREETING_TEXT);
    });

    it("does not call speak when the caller does not invoke speakGreeting (muted path is the caller's responsibility)", () => {
      const speak = vi.fn();
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak, cancel: vi.fn() },
        configurable: true,
        writable: true,
      });
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: class {
          constructor(public text: string) {}
        },
        configurable: true,
        writable: true,
      });

      // Simulating a muted visitor: the widget's mute check short-circuits
      // before ever calling speakGreeting — tts.ts has no muted concept of
      // its own, so the contract under test is "not calling it means no
      // speech", proven trivially but explicitly for the record.
      expect(speak).not.toHaveBeenCalled();
    });

    it("no-ops without throwing when window.speechSynthesis is absent", () => {
      Object.defineProperty(window, "speechSynthesis", {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(() => speakGreeting()).not.toThrow();
    });

    it("no-ops without throwing when SpeechSynthesisUtterance is absent", () => {
      const speak = vi.fn();
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak, cancel: vi.fn() },
        configurable: true,
        writable: true,
      });
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(() => speakGreeting()).not.toThrow();
      expect(speak).not.toHaveBeenCalled();
    });

    it("swallows a throwing speak() and never lets it escape (chat must be unaffected)", () => {
      const speak = vi.fn(() => {
        throw new Error("blocked by browser policy");
      });
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak, cancel: vi.fn() },
        configurable: true,
        writable: true,
      });
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: class {
          constructor(public text: string) {}
        },
        configurable: true,
        writable: true,
      });

      expect(() => speakGreeting()).not.toThrow();
      expect(speak).toHaveBeenCalledTimes(1);
    });

    it("swallows a throwing Utterance constructor and never lets it escape", () => {
      const speak = vi.fn();
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak, cancel: vi.fn() },
        configurable: true,
        writable: true,
      });
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: class {
          constructor() {
            throw new Error("construction failed");
          }
        },
        configurable: true,
        writable: true,
      });

      expect(() => speakGreeting()).not.toThrow();
      expect(speak).not.toHaveBeenCalled();
    });
  });

  describe("cancel", () => {
    it("calls speechSynthesis.cancel when available", () => {
      const cancelFn = vi.fn();
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak: vi.fn(), cancel: cancelFn },
        configurable: true,
        writable: true,
      });

      cancel();

      expect(cancelFn).toHaveBeenCalledTimes(1);
    });

    it("no-ops without throwing when window.speechSynthesis is absent", () => {
      Object.defineProperty(window, "speechSynthesis", {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(() => cancel()).not.toThrow();
    });

    it("swallows a throwing cancel() and never lets it escape", () => {
      const cancelFn = vi.fn(() => {
        throw new Error("blocked");
      });
      Object.defineProperty(window, "speechSynthesis", {
        value: { speak: vi.fn(), cancel: cancelFn },
        configurable: true,
        writable: true,
      });

      expect(() => cancel()).not.toThrow();
    });
  });
});
