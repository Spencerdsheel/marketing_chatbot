/**
 * Stat-tile row for the analytics dashboard, restyled to match design spec
 * screen 5b (Ink & Citron, HANDOFF-SPEC.md §3): 4 stat cards, the last one
 * on an ink surface with a citron headline number.
 *
 * Every number here is a REAL metric already computed by
 * `services/api/src/api/analytics/repository.py` (S13.5 decision 4/6) --
 * no invented figures. Where 5b's mock text names a metric this backend
 * does not compute ("Leads captured"), that card is intentionally NOT
 * built here (see the honest-gap accounting in the restyle report) rather
 * than faked with borrowed data from another module.
 *
 * Card mapping (5b mock -> real field):
 *   1. CONVERSATIONS      -> totals.conversations
 *   2. ANSWERED W/O ESCALATION (deflection) -> deflectionRate * totals.conversations
 *   3. GROUNDED RATE       -> groundedRate (share of answers grounded in retrieved knowledge)
 *   4. CALLS BOOKED (ink/citron) -> schedule.conversions
 *
 * Each rate-based card renders `formatRate`'s "No data" state visibly
 * (never a fabricated 0%) -- the load-bearing no-silent-fallback property
 * (CLAUDE.md §3, Decision 6a).
 */
import { formatRate, type AnalyticsOverview } from "@/lib/analytics";

function StatCard({
  label,
  value,
  caption,
  captionTone = "muted",
  ink = false,
}: {
  label: string;
  value: string;
  caption: string;
  captionTone?: "muted" | "positive" | "negative";
  ink?: boolean;
}) {
  const captionColor = ink
    ? "text-[#9b9c93]"
    : captionTone === "positive"
      ? "text-[#1f6a2f]"
      : captionTone === "negative"
        ? "text-[#c2452d]"
        : "text-[#70716a]";

  return (
    <div
      className={
        ink
          ? "flex flex-col gap-1.5 rounded-[14px] bg-[#191a17] p-4"
          : "flex flex-col gap-1.5 rounded-[14px] border border-[#e7e7e2] p-4"
      }
    >
      <span
        className={
          ink
            ? "text-[11.5px] font-semibold text-[#9b9c93]"
            : "text-[11.5px] font-semibold text-[#70716a]"
        }
      >
        {label.toUpperCase()}
      </span>
      <span
        className={
          ink
            ? "text-[30px] font-bold tabular-nums text-[#e4f222]"
            : "text-[30px] font-bold tabular-nums text-[#191a17]"
        }
      >
        {value}
      </span>
      <span className={`text-[11.5px] font-semibold ${captionColor}`}>{caption}</span>
    </div>
  );
}

/**
 * Raw supporting totals (user/bot/decided turns, schedule CTA count) that
 * back the headline cards -- kept as a compact secondary strip rather than
 * dropped, since they're real and useful for debugging a rate that looks
 * off, but they are not part of 5b's 4-card hero row.
 */
function MiniTotal({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-[10px] border border-[#f0f0ea] bg-[#f7f7f3] px-3 py-2">
      <span className="text-[10.5px] font-semibold tracking-wide text-[#96978e] uppercase">
        {label}
      </span>
      <span className="text-[15px] font-bold tabular-nums text-[#191a17]">{value}</span>
    </div>
  );
}

export function AnalyticsCards({ data }: { data: AnalyticsOverview }) {
  const deflectedCount =
    data.deflectionRate === null
      ? null
      : Math.round(data.deflectionRate * data.totals.conversations);

  return (
    <div className="flex flex-col gap-3">
      <div
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
        role="group"
        aria-label="Analytics summary stats"
      >
        <StatCard
          label="Conversations"
          value={data.totals.conversations.toLocaleString()}
          caption={`${data.totals.userTurns.toLocaleString()} visitor turns in this window`}
        />
        <StatCard
          label="Answered without escalation"
          value={formatRate(data.deflectionRate)}
          caption={
            data.deflectionRate === null
              ? "No conversations in this window."
              : `${deflectedCount?.toLocaleString()} of ${data.totals.conversations.toLocaleString()} conversations deflected`
          }
          captionTone={data.deflectionRate === null ? "muted" : "positive"}
        />
        <StatCard
          label="Grounded rate"
          value={formatRate(data.groundedRate)}
          caption={
            data.groundedRate === null
              ? "No answered turns in this window."
              : "Share of answers grounded in retrieved knowledge"
          }
          captionTone={data.groundedRate === null ? "muted" : "positive"}
        />
        <StatCard
          label="Calls booked"
          value={data.schedule.conversions.toLocaleString()}
          caption={
            data.schedule.ctaConversations === 0
              ? "No scheduling CTA shown in this window."
              : `${formatRate(data.schedule.conversionRate)} of ${data.schedule.ctaConversations.toLocaleString()} CTA conversations (approximate)`
          }
          ink
        />
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <MiniTotal label="User turns" value={data.totals.userTurns} />
        <MiniTotal label="Bot turns" value={data.totals.botTurns} />
        <MiniTotal label="Decided bot turns" value={data.totals.decidedBotTurns} />
        <MiniTotal label="Schedule CTAs shown" value={data.schedule.ctaConversations} />
      </div>
    </div>
  );
}
