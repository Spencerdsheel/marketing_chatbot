import { describe, expect, it } from "vitest";
import { buildPipelineDashboard, DASHBOARD_STAGES } from "@/lib/dashboard";
import type { LeadsResult } from "@/lib/leads";

function result(total: number): LeadsResult {
  return { status: "ok", items: [], total, limit: 25, offset: 0 };
}

describe("buildPipelineDashboard", () => {
  it("uses the four canonical visible stages in 3a pipeline order", () => {
    expect(DASHBOARD_STAGES.map((stage) => stage.key)).toEqual([
      "captured",
      "qualified",
      "contacted",
      "converted",
    ]);
  });

  it("derives totals and qualification rate only from live stage results", () => {
    const dashboard = buildPipelineDashboard([result(5), result(3), result(2), result(1)]);

    expect(dashboard.status).toBe("ok");
    if (dashboard.status === "ok") {
      expect(dashboard.columns.map((column) => column.total)).toEqual([5, 3, 2, 1]);
      expect(dashboard.metrics).toEqual({
        total: 11,
        active: 10,
        converted: 1,
        qualificationRate: 6 / 11,
      });
    }
  });

  it("preserves a stage failure rather than rendering partial or fallback data", () => {
    const dashboard = buildPipelineDashboard([
      result(1),
      { status: "error", message: "Lead access denied", correlationId: "corr-42" },
      result(1),
      result(1),
    ]);

    expect(dashboard).toEqual({
      status: "error",
      message: "Lead access denied",
      correlationId: "corr-42",
    });
  });

  it("keeps a zero-denominator qualification rate unknown", () => {
    const dashboard = buildPipelineDashboard([result(0), result(0), result(0), result(0)]);

    expect(dashboard.status).toBe("ok");
    if (dashboard.status === "ok") {
      expect(dashboard.metrics.qualificationRate).toBeNull();
    }
  });
});
