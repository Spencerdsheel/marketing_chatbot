/**
 * Honest "not available" card (CLAUDE.md §3 no-silent-fallback: never
 * serve fake/sample chart data when the backing metric doesn't exist --
 * fail explicitly and visibly instead). Used for the two 5b chart slots
 * this backend cannot back with a real metric: "Top questions" (literal
 * question text/frequency isn't tracked -- only closed-set intent
 * categories, see `distribution-bars.tsx`) and "Peak hours" (the analytics
 * repository only buckets by `day`/`week`; there is no hourly aggregation,
 * `_VALID_BUCKETS = {"day", "week"}` in
 * `services/api/src/api/analytics/repository.py`).
 */
export function UnavailableCard({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-dashed border-[#d5d5cb] p-[18px]">
      <span className="text-sm font-bold text-[#191a17]">{title}</span>
      <p role="status" className="text-[12.5px] leading-relaxed text-[#70716a]">
        Not available yet. {reason}
      </p>
    </div>
  );
}
