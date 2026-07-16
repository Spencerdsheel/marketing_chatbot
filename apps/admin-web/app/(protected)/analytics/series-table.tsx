/**
 * Renders the time-bucketed `series` as a compact `shadcn/ui` table
 * (S13.5.md decision 4/7) -- reusing the S13.4 `table` primitive rather
 * than a charting library. Pure presentation, no interactivity.
 */
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AnalyticsOverview } from "@/lib/analytics";

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function SeriesTable({ series }: { series: AnalyticsOverview["series"] }) {
  if (series.length === 0) {
    return <p className="text-sm text-muted-foreground">No time-series data for this window.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Bucket start</TableHead>
          <TableHead>Conversations</TableHead>
          <TableHead>Answers</TableHead>
          <TableHead>Escalations</TableHead>
          <TableHead>Bookings</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {series.map((bucket) => (
          <TableRow key={bucket.bucketStart}>
            <TableCell className="font-medium">{formatDate(bucket.bucketStart)}</TableCell>
            <TableCell>{bucket.conversations}</TableCell>
            <TableCell>{bucket.answers}</TableCell>
            <TableCell>{bucket.escalations}</TableCell>
            <TableCell>{bucket.bookings}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
