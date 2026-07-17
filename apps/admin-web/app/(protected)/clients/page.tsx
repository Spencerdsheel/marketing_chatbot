/**
 * PLATFORM_ADMIN "Clients" tile list (S13.7). This is the top-level area a
 * platform admin lands on (D4) -- a tile per onboarded client, each linking
 * into that client's management area (`/clients/{tenantId}/settings`), plus
 * the "Add client" platform-level action (D7). Gated by `requireRole`
 * (D6) -- a CLIENT_ADMIN/CLIENT_AGENT who forces this URL is redirected to
 * their own dashboard (mirrors `tenants/new/page.tsx`'s existing pattern).
 *
 * Honest empty/error states (no fabricated client rows) -- `listClients()`
 * (lib/clients.ts) already returns a discriminated result for exactly this.
 */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { requireRole } from "@/lib/auth";
import { listClients } from "@/lib/clients";
import { OnboardClientForm } from "@/app/(protected)/clients/onboard-client-form";

export default async function ClientsPage() {
  await requireRole("PLATFORM_ADMIN");

  const result = await listClients();

  return (
    <div className="flex flex-1 flex-col items-center gap-6 p-8">
      <div className="grid w-full max-w-5xl gap-6 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Clients</CardTitle>
            <CardDescription>
              Every onboarded client. Select one to manage its bot, leads, analytics, and
              knowledge base.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {result.status === "error" ? (
              <p
                role="alert"
                className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
              >
                {result.message}
                {result.correlationId ? (
                  <span className="block text-xs text-destructive/80">
                    Correlation ID: {result.correlationId}
                  </span>
                ) : null}
              </p>
            ) : result.items.length === 0 ? (
              <p role="status" className="rounded-md border border-input bg-muted/50 p-4 text-sm">
                No clients yet — use &quot;Add client&quot; to onboard the first one.
              </p>
            ) : (
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {result.items.map((client) => (
                  <li key={client.tenantId}>
                    <Link
                      href={`/clients/${client.tenantId}/settings`}
                      className="flex flex-col gap-1 rounded-md border border-input p-4 transition-colors hover:bg-muted/50"
                    >
                      <span className="font-medium">{client.name}</span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {client.slug}
                      </span>
                      {!client.enabled ? (
                        <span className="text-xs text-destructive">Disabled</span>
                      ) : null}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Add client</CardTitle>
            <CardDescription>
              Creates a new tenant and its first CLIENT_ADMIN user. The client key (and generated
              admin password, if any) are shown exactly once — they cannot be recovered later.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <OnboardClientForm />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
