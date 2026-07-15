/**
 * Client onboarding screen (S13.2). PLATFORM_ADMIN-only -- gated by
 * `requireRole` (decision 1), a server-component-level check colocated with
 * this screen rather than a `proxy.ts` route->role map (see lib/auth.ts's
 * `requireRole` docstring for why).
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
import { OnboardForm } from "@/app/(protected)/tenants/new/onboard-form";

export default async function OnboardTenantPage() {
  await requireRole("PLATFORM_ADMIN");

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <div className="w-full max-w-xl">
        <Link href="/" className="text-sm text-muted-foreground hover:underline">
          ← Back to console
        </Link>
      </div>
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>Onboard a client</CardTitle>
          <CardDescription>
            Creates a new tenant and its first CLIENT_ADMIN user. The tenant&apos;s client key
            (and generated admin password, if any) are shown exactly once after creation --
            they cannot be recovered later.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <OnboardForm />
        </CardContent>
      </Card>
    </div>
  );
}
