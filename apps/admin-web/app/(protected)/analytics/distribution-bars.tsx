/**
 * Renders a `Record<string, number>` distribution (intent or decision) as a
 * descending-count progress list, restyled to Ink & Citron's "top-questions
 * progress list" visual language (5b) -- track + fill bar, count at right,
 * label at left, top item's fill in citron.
 *
 * Honesty note: 5b's mock literally shows question text ("Pricing &
 * plans", "Integrations", ...). This backend does not track per-question
 * text/frequency -- `intent_distribution` is a closed-set of *intent
 * categories* (repository.py `_fetch_message_facts`, e.g. "pricing",
 * "unclassified"), not verbatim visitor questions. Labeling this list
 * "Top questions" would misrepresent what's real, so the caller titles it
 * "Top intents" / "Decision outcomes" instead -- see the separate
 * `TopQuestionsUnavailable` card for the honest gap on literal top
 * questions.
 */
export function DistributionBars({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = entries.length > 0 ? Math.max(...entries.map(([, count]) => count)) : 0;

  return (
    <div className="flex flex-col gap-3 rounded-[14px] border border-[#e7e7e2] p-[18px]">
      <span className="text-sm font-bold text-[#191a17]">{title}</span>
      {entries.length === 0 ? (
        <p role="status" className="text-sm text-[#70716a]">
          No data for this window.
        </p>
      ) : (
        <ul className="flex flex-col gap-2.5 text-[12.5px] text-[#45463f]">
          {entries.map(([label, count], i) => {
            const widthPct = max > 0 ? (count / max) * 100 : 0;
            const isTop = i === 0;
            return (
              <li key={label} className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate">{label}</span>
                  <span className="font-bold text-[#191a17] tabular-nums">{count}</span>
                </div>
                <div className="h-[7px] overflow-hidden rounded-full bg-[#f0f0ea]">
                  <div
                    role="img"
                    aria-label={`${label}: ${count} of ${max} (top value)`}
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(widthPct, count > 0 ? 4 : 0)}%`,
                      backgroundColor: isTop ? "#e4f222" : "#191a17",
                    }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
