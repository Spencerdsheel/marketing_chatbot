/**
 * Stat-tile grid for the four headline rates + raw totals + schedule
 * counts (S13.5.md decision 4/6). Each rate tile renders via `formatRate`
 * so a `null` denominator shows as a visibly muted "No data" -- never a
 * fabricated "0%" (the load-bearing no-silent-fallback property). The
 * schedule-conversion tile carries an "approximate" caption (Decision 6 /
 * Investigation -- the visitor_id-correlated attribution, S11.2 decision 6).
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRate, type AnalyticsOverview } from "@/lib/analytics";

function RateTile({
  label,
  caption,
  rate,
  approximate,
}: {
  label: string;
  caption: string;
  rate: number | null;
  approximate?: boolean;
}) {
  const formatted = formatRate(rate);
  const isNoData = rate === null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p
          className={
            isNoData ? "text-2xl font-semibold text-muted-foreground" : "text-2xl font-semibold"
          }
        >
          {formatted}
        </p>
        <p className="text-xs text-muted-foreground">
          {isNoData ? "No qualifying turns in this window." : caption}
          {approximate ? " (approximate)" : ""}
        </p>
      </CardContent>
    </Card>
  );
}

function TotalTile({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

export function AnalyticsCards({ data }: { data: AnalyticsOverview }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <RateTile
          label="Fallback rate"
          caption="Share of hand-offs to a human."
          rate={data.fallbackRate}
        />
        <RateTile
          label="Deflection rate"
          caption="Share of turns the bot resolved without escalating."
          rate={data.deflectionRate}
        />
        <RateTile
          label="Grounded rate"
          caption="Share of answers grounded in retrieved knowledge."
          rate={data.groundedRate}
        />
        <RateTile
          label="Schedule conversion"
          caption="Share of scheduling CTAs that led to a booking."
          rate={data.schedule.conversionRate}
          approximate
        />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <TotalTile label="Conversations" value={data.totals.conversations} />
        <TotalTile label="User turns" value={data.totals.userTurns} />
        <TotalTile label="Bot turns" value={data.totals.botTurns} />
        <TotalTile label="Decided bot turns" value={data.totals.decidedBotTurns} />
        <TotalTile label="Schedule CTAs shown" value={data.schedule.ctaConversations} />
        <TotalTile label="Bookings" value={data.schedule.conversions} />
      </div>
    </div>
  );
}
