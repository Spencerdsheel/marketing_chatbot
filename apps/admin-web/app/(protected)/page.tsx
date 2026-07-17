/**
 * Placeholder authenticated shell (S13.1 scope item 6). Proves the auth
 * bridge end-to-end: displays the caller's real claims decoded from the
 * cookie admin-api issued. No feature screens yet -- those start in
 * S13.2+, all mounting under this same (protected) route group.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, buttonVariants } from "@/components/ui/button";
import { getClaims } from "@/lib/auth";
import { getProfile } from "@/lib/profile";
import { logout } from "@/app/(protected)/actions";

export default async function ProtectedHomePage() {
  const claims = await getClaims();
  if (!claims) {
    // Layout already guards this, but keep the page self-sufficient.
    redirect("/login");
  }

  const profile = await getProfile();
  // Falls back to the subject (user id) if the display-only profile cookie
  // is somehow absent (see lib/profile.ts) -- the auth gate above never
  // depends on this value, only the on-screen label does.
  const identityLabel = profile?.email ?? claims.subject;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-8 text-center">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Admin console</h1>
        <p className="text-muted-foreground">
          Logged in as <span className="font-medium">{identityLabel}</span>,
          role <span className="font-medium">{claims.role}</span>, tenant{" "}
          <span className="font-medium">{claims.tenantId ?? "platform"}</span>
        </p>
      </div>
      {claims.role === "PLATFORM_ADMIN" ? (
        <Link href="/clients" className={buttonVariants({ variant: "secondary" })}>
          Clients
        </Link>
      ) : null}
      {claims.role === "CLIENT_ADMIN" ? (
        <Link href="/knowledge" className={buttonVariants({ variant: "secondary" })}>
          Upload knowledge
        </Link>
      ) : null}
      {claims.role === "CLIENT_ADMIN" || claims.role === "CLIENT_AGENT" ? (
        <Link href="/leads" className={buttonVariants({ variant: "secondary" })}>
          Review leads
        </Link>
      ) : null}
      {claims.role === "CLIENT_ADMIN" || claims.role === "CLIENT_AGENT" ? (
        <Link href="/analytics" className={buttonVariants({ variant: "secondary" })}>
          View analytics
        </Link>
      ) : null}
      {claims.role === "CLIENT_ADMIN" || claims.role === "CLIENT_AGENT" ? (
        <Link href="/settings" className={buttonVariants({ variant: "secondary" })}>
          Bot settings
        </Link>
      ) : null}
      <form action={logout}>
        <Button type="submit" variant="outline">
          Log out
        </Button>
      </form>
    </div>
  );
}
