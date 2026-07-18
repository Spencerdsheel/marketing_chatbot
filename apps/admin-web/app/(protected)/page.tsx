import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight, CalendarDays, CircleAlert, UserRound } from "lucide-react";
import { getClaims } from "@/lib/auth";
import { getDashboardPipeline, type PipelineColumn } from "@/lib/dashboard";

function formatRate(rate: number | null): string {
  if (rate === null) return "No data";
  return `${Math.round(rate * 100)}%`;
}

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
          <section aria-label="Lead pipeline overview" className="mt-6 rounded-2xl bg-[#191a17] p-5 text-white sm:p-7">
            <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
              <div className="border-b border-white/15 pb-5 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-6">
                <p className="text-sm font-semibold">Pipeline leads</p>
                <p className="mt-5 text-4xl font-bold tracking-[-0.05em] tabular-nums">{result.metrics.total}</p>
                <p className="mt-2 text-xs text-[#bfc0b7]">Across the four active stages</p>
              </div>
              <div className="border-b border-white/15 pb-5 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-6">
                <p className="text-sm font-semibold">Qualification rate</p>
                <p className="mt-5 text-4xl font-bold tracking-[-0.05em] tabular-nums text-[#e4f222]">{formatRate(result.metrics.qualificationRate)}</p>
                <p className="mt-2 text-xs text-[#bfc0b7]">Reached qualified or later</p>
              </div>
              <div className="border-b border-white/15 pb-5 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-6">
                <p className="text-sm font-semibold">Active leads</p>
                <p className="mt-5 text-4xl font-bold tracking-[-0.05em] tabular-nums">{result.metrics.active}</p>
                <p className="mt-2 text-xs text-[#bfc0b7]">Captured, qualified, or contacted</p>
              </div>
              <div>
                <p className="text-sm font-semibold">Converted</p>
                <p className="mt-5 text-4xl font-bold tracking-[-0.05em] tabular-nums text-[#e4f222]">{result.metrics.converted}</p>
                <p className="mt-2 text-xs text-[#bfc0b7]">Current converted stage</p>
              </div>
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
