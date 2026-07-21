import { describe, expect, it } from "vitest";
import {
  shouldShowSourcesAffordance,
  sourceBodyText,
  sourceMetaLabel,
  sourcesToggleLabel,
} from "@/app/(protected)/conversations/message-sources";

/**
 * Pure-logic coverage for the "View sources" affordance (SR-2). This repo
 * has no DOM/React-testing-library dependency wired up (vitest.config.ts
 * only includes `**\/*.test.ts`, `environment: "node"`), so -- mirroring
 * `schedule-polling.test.ts`'s pattern -- the affordance's gating and
 * text-rendering logic is exported as pure functions from
 * `message-sources.tsx` and tested directly here, rather than rendering JSX.
 */
describe("shouldShowSourcesAffordance", () => {
  it("shows for a bot message with sourceCount > 0 (role='bot')", () => {
    expect(shouldShowSourcesAffordance("bot", 3)).toBe(true);
  });

  it("shows for a bot message with sourceCount > 0 (role='assistant')", () => {
    expect(shouldShowSourcesAffordance("assistant", 1)).toBe(true);
  });

  it("does NOT show for a bot message with sourceCount === 0 (chit-chat/escalate)", () => {
    expect(shouldShowSourcesAffordance("bot", 0)).toBe(false);
  });

  it("does NOT show for a visitor/user message even if sourceCount > 0", () => {
    expect(shouldShowSourcesAffordance("user", 3)).toBe(false);
    expect(shouldShowSourcesAffordance("visitor", 3)).toBe(false);
  });
});

describe("sourcesToggleLabel", () => {
  it("renders the count", () => {
    expect(sourcesToggleLabel(5)).toBe("View sources (5)");
    expect(sourcesToggleLabel(0)).toBe("View sources (0)");
  });
});

describe("sourceBodyText", () => {
  it("renders the real chunk content for a resolved source", () => {
    expect(sourceBodyText({ resolved: true, content: "Real chunk text." })).toBe("Real chunk text.");
  });

  it("renders the honest 'no longer in the knowledge base' line for an unresolved source -- not blank/placeholder", () => {
    const text = sourceBodyText({ resolved: false, content: null });
    expect(text).toBe("source no longer in the knowledge base");
    expect(text).not.toBe("");
  });

  it("treats resolved=true with content=null as unresolved (defensive -- never renders blank)", () => {
    const text = sourceBodyText({ resolved: true, content: null });
    expect(text).toBe("source no longer in the knowledge base");
  });
});

describe("sourceMetaLabel", () => {
  it("includes doc_id, chunk_id, and the echoed score", () => {
    expect(sourceMetaLabel({ docId: "doc-1", chunkId: "c1", score: 0.834 })).toBe(
      "doc-1 · c1 · score 0.83"
    );
  });

  it("omits the score segment when score is null -- never fabricates a verdict", () => {
    expect(sourceMetaLabel({ docId: "doc-1", chunkId: "c1", score: null })).toBe("doc-1 · c1");
  });
});
