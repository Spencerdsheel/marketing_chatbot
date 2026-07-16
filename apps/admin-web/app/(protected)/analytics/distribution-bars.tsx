/**
 * Renders a `Record<string, number>` distribution (intent or decision) as
 * descending-count CSS horizontal bars -- no charting library (S13.5.md
 * decision 4/7). Pure presentation, no interactivity, no `"use client"`.
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
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No data for this window.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map(([label, count]) => {
            const widthPct = max > 0 ? (count / max) * 100 : 0;
            return (
              <li key={label} className="flex items-center gap-2 text-sm">
                <span className="w-32 shrink-0 truncate text-muted-foreground">{label}</span>
                <div className="h-3 flex-1 overflow-hidden rounded bg-muted">
                  <div
                    role="img"
                    aria-label={`${label}: ${count}`}
                    className="h-full rounded bg-primary"
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right tabular-nums">{count}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
