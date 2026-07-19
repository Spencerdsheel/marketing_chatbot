/**
 * Server-side data fetch for the 4b drawer. `page.tsx`/`clients/[tenantId]/
 * leads/page.tsx` read `?lead=<id>&tab=<tab>` from `searchParams` and, when
 * present, render this async server component -- it fetches the lead detail
 * (+ activities, needed by both the Activity and Notes tabs) and hands them
 * to the client `LeadDrawer` for interactivity (tabs, Esc/focus).
 */
import { getLeadActivities, getLeadDetail } from "@/lib/leads";
import { LeadDrawer, TABS, type Tab } from "@/app/(protected)/leads/lead-drawer";

function isTab(value: string | undefined): value is Tab {
  return !!value && (TABS as readonly string[]).includes(value);
}

export async function LeadDrawerContainer({
  leadId,
  rawTab,
  basePath,
  tenantId,
}: {
  leadId: string;
  rawTab: string | undefined;
  basePath: string;
  tenantId?: string;
}) {
  const tab: Tab = isTab(rawTab) ? rawTab : "transcript";

  const detailResult = await getLeadDetail(leadId, tenantId);
  // Activity/Notes both need the same timeline; Details/Transcript don't, so
  // skip the extra round trip when they're not the active tab.
  const activitiesResult =
    tab === "activity" || tab === "notes" ? await getLeadActivities(leadId, tenantId) : null;

  return (
    <LeadDrawer
      leadId={leadId}
      tab={tab}
      detailResult={detailResult}
      activitiesResult={activitiesResult}
      basePath={basePath}
      tenantId={tenantId}
    />
  );
}
