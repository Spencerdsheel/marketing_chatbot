import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight, CalendarDays, CircleAlert, UserRound } from "lucide-react";
import { getClaims } from "@/lib/auth";
import { getDashboardPipeline, type PipelineColumn } from "@/lib/dashboard";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function LeadCard({ lead, featured }: { lead: PipelineColumn["items"][number]; featured: boolean }) {
  return (
    <article
      className={
        featured
          ? "flex flex-col gap-3 rounded-2xl bg-[#191a17] p-4 text-white shadow-[0_10px_26px_rgba(25,26,23,0.2)]"
          : "flex flex-col gap-3 rounded-2xl border border-[#e7e7e2] bg-white p-4"
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-bold">{lead.name}</h3>
          <p className={featured ? "mt-1 truncate text-xs text-[#c6c7bd]" : "mt-1 truncate text-xs text-[#70716a]"}>
            {lead.source}
          </p>
        </div>
        <span
          className={
            featured
              ? "rounded-md bg-[#e4f222] px-1.5 py-0.5 text-[11px] font-bold text-[#191a17]"
              : "rounded-md bg-[#f2f2ec] px-1.5 py-0.5 text-[11px] font-semibold text-[#5a5b54]"
          }
        >
          {lead.status}
        </span>
      </div>
      <dl className={featured ? "grid gap-2 border-t border-white/15 pt-3 text-xs text-[#c6c7bd]" : "grid gap-2 border-t border-[#e7e7e2] pt-3 text-xs text-[#70716a]"}>
        <div className="flex items-center gap-2">
          <CalendarDays aria-hidden className="size-3.5" />
          <dt className="sr-only">Captured</dt>
          <dd>{formatDate(lead.createdAt)}</dd>
        </div>
        {lead.qualificationScore !== null ? (
          <div className="flex items-center gap-2">
            <UserRound aria-hidden className="size-3.5" />
            <dt className="sr-only">Qualification score</dt>
            <dd>Score {lead.qualificationScore}</dd>
          </div>
        ) : null}
        {lead.assignedAgentId ? (
          <div className="flex items-center gap-2">
            <UserRound aria-hidden className="size-3.5" />
            <dt className="sr-only">Assigned agent</dt>
            <dd className="truncate">Assigned</dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

/**
 * Per-stage lead counts as paired bars, matching the 3a prototype's "New
 * leads" chart shape (dark #3d3e38 + citron #e4f222 per group). We have no
 * time-series metric to back a day-by-day chart, so each group is a pipeline
 * stage instead of a weekday: the dark bar is that stage's share of the
 * total pipeline, the citron bar is its share of the active (non-terminal)
 * leads. Both are derived from `getDashboardPipeline`'s real column totals
 * -- nothing here is fabricated.
 */
function StageDistributionChart({ columns }: { columns: PipelineColumn[] }) {
  const total = columns.reduce((sum, column) => sum + column.total, 0);
  const activeTotal = columns
    .filter((column) => column.key !== "converted")
    .reduce((sum, column) => sum + column.total, 0);
  const maxTotal = Math.max(...columns.map((column) => column.total), 1);

  return (
    <div>
      <p className="text-[13.5px] font-semibold text-[#c6c7bd]">Pipeline by stage</p>
      <div className="mt-4 flex items-end gap-3.5" style={{ height: 110 }}>
        {columns.map((column) => {
          const shareOfTotal = total > 0 ? (column.total / maxTotal) * 100 : 0;
          const shareOfActive =
            column.key !== "converted" && activeTotal > 0 ? (column.total / maxTotal) * 100 : 0;
          return (
            <div key={column.key} className="flex flex-col items-center gap-1.5">
              <div className="flex items-end gap-[3px]" style={{ height: 90 }}>
                <div
                  role="img"
                  aria-label={`${column.label}: ${column.total} leads`}
                  className="w-3 rounded-[3px] bg-[#3d3e38]"
                  style={{ height: `${Math.max(shareOfTotal, column.total > 0 ? 6 : 0)}%` }}
                />
                <div
                  className="w-3 rounded-[3px] bg-[#e4f222]"
                  style={{ height: `${Math.max(shareOfActive, shareOfActive > 0 ? 6 : 0)}%` }}
                />
              </div>
              <div className="text-[11px] text-[#9b9c93]">{column.label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Half-donut built from a clipped conic-gradient ring, per HANDOFF-SPEC's 3a
 * recipe. Driven entirely by the real `qualificationRate` metric (already
 * computed in lib/dashboard.ts as progressed / total); renders a flat empty
 * ring rather than a fabricated percentage when the denominator is zero.
 */
function QualificationDonut({ rate }: { rate: number | null }) {
  const pct = rate === null ? 0 : Math.round(rate * 100);
  const sweepDeg = (pct / 100) * 180;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative overflow-hidden" style={{ width: 170, height: 92 }}>
        <div
          className="absolute top-0 rounded-full"
          style={{
            width: 170,
            height: 170,
            background: `conic-gradient(from -90deg, #e4f222 0deg ${sweepDeg}deg, #3d3e38 ${sweepDeg}deg 180deg, transparent 180deg)`,
          }}
        />
        <div
          className="absolute rounded-full bg-[#191a17]"
          style={{ width: 126, height: 126, top: 22, left: 22 }}
        />
        <div className="absolute inset-x-0 bottom-0 text-center text-2xl leading-none font-bold text-white">
          {rate === null ? "–" : `${pct}%`}
        </div>
      </div>
      <div className="text-[13px] text-[#9b9c93]">Qualification rate</div>
    </div>
  );
}

function PipelineColumn({ column }: { column: PipelineColumn }) {
  const featured = column.key === "contacted";
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-heading text-xl font-semibold tracking-[-0.03em]">{column.label}</h2>
        <Link
          href={`/leads?stage=${column.key}`}
          className="rounded-lg border border-[#e7e7e2] px-2 py-1 text-xs text-[#5a5b54] transition-colors hover:bg-[#f7f7f3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
        >
          {column.total} total
        </Link>
      </div>
      {column.items.length === 0 ? (
        <p role="status" className="rounded-2xl border border-dashed border-[#d8d9d0] bg-white/70 p-4 text-sm text-[#70716a]">
          No {column.label.toLowerCase()} leads yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {column.items.slice(0, 3).map((lead) => (
            <LeadCard key={lead.leadId} lead={lead} featured={featured} />
          ))}
        </div>
      )}
    </section>
  );
}

export default async function ProtectedHomePage() {
  const claims = await getClaims();
  if (!claims) {
    redirect("/login");
  }
  if (claims.role === "PLATFORM_ADMIN") redirect("/clients");
  if (claims.role !== "CLIENT_ADMIN" && claims.role !== "CLIENT_AGENT") redirect("/login");

  const result = await getDashboardPipeline();

  return (
    <main className="flex flex-1 flex-col px-4 py-5 sm:px-6 lg:px-7 lg:py-6">
      <header className="flex flex-col gap-4 border-b border-[#e7e7e2] pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.08em] text-[#96978e] uppercase">Lead workspace</p>
          <h1 className="mt-1 font-heading text-2xl font-bold tracking-[-0.04em] sm:text-[28px]">Dashboard</h1>
        </div>
        <Link
          href="/leads"
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#191a17] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#30312d] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
        >
          Review leads
          <ArrowRight aria-hidden className="size-4" />
        </Link>
      </header>

      {result.status === "error" ? (
        <div role="alert" className="mt-6 rounded-2xl border border-[#c2452d]/30 bg-[#fff3ee] p-4 text-sm text-[#8f2e1c]">
          <div className="flex gap-2">
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            <div>
              <p className="font-semibold">The lead pipeline could not be loaded.</p>
              <p className="mt-1">{result.message}</p>
              {result.correlationId ? <p className="mt-1 text-xs">Correlation ID: {result.correlationId}</p> : null}
            </div>
          </div>
        </div>
      ) : (
        <>
          <section
            aria-label="Lead pipeline overview"
            className="mt-6 grid gap-8 rounded-2xl bg-[#191a17] p-5 text-white sm:p-7 lg:grid-cols-[1.2fr_1fr_0.9fr_0.9fr] lg:items-center"
          >
            <StageDistributionChart columns={result.columns} />
            <QualificationDonut rate={result.metrics.qualificationRate} />
            <div>
              <p className="text-[13.5px] font-semibold text-[#c6c7bd]">Pipeline leads</p>
              <p className="mt-2.5 text-4xl leading-none font-bold tracking-[-0.05em] tabular-nums text-white">
                {result.metrics.total}
              </p>
              <p className="mt-2.5 text-[13.5px] leading-[1.4] text-[#9b9c93]">
                Across the four
                <br />
                active stages
              </p>
            </div>
            <div>
              <p className="text-[13.5px] font-semibold text-[#c6c7bd]">Converted</p>
              <p className="mt-2.5 text-4xl leading-none font-bold tracking-[-0.05em] tabular-nums text-[#e4f222]">
                {result.metrics.converted}
              </p>
              <p className="mt-2.5 text-[13.5px] leading-[1.4] text-[#9b9c93]">
                Current converted
                <br />
                stage
              </p>
            </div>
          </section>

          <section aria-label="Lead pipeline" className="mt-7 grid gap-7 md:grid-cols-2 2xl:grid-cols-4">
            {result.columns.map((column) => <PipelineColumn key={column.key} column={column} />)}
          </section>
        </>
      )}
    </main>
  );
}
