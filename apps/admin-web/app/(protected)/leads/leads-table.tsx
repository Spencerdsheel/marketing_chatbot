/**
 * Renders a page of leads as a `shadcn/ui` table (S13.4 decision 4). No
 * interactivity of its own -- a pure presentation component fed rows the
 * server component (`page.tsx`) already fetched. Columns render exactly the
 * leak-free `LeadListItem` fields: Name, Email, Phone, Stage, Status, Score,
 * Source, Created, Assigned agent (id, display-only, no name lookup --
 * Decision 5, no agent-directory endpoint exists).
 */
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LeadListItem } from "@/lib/leads";

const MUTED = <span className="text-muted-foreground">—</span>;

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function LeadsTable({ items }: { items: LeadListItem[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Email</TableHead>
          <TableHead>Phone</TableHead>
          <TableHead>Stage</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Assigned</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((lead) => (
          <TableRow key={lead.leadId}>
            <TableCell className="font-medium">{lead.name}</TableCell>
            <TableCell>{lead.email}</TableCell>
            <TableCell>{lead.phone ?? MUTED}</TableCell>
            <TableCell>{lead.stage}</TableCell>
            <TableCell>{lead.status}</TableCell>
            <TableCell>{lead.qualificationScore ?? MUTED}</TableCell>
            <TableCell>{lead.source}</TableCell>
            <TableCell>{formatDate(lead.createdAt)}</TableCell>
            <TableCell className="text-muted-foreground">{lead.assignedAgentId ?? MUTED}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
