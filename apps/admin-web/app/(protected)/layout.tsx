/**
 * Wraps every authenticated route. Re-confirms claims server-side via
 * `cookies()` + local decode as defense-in-depth alongside `proxy.ts`
 * (S13.1 decision 3) -- proxy is a fast pre-render gate, this is the
 * server-component-level check that runs even if proxy's matcher were ever
 * misconfigured for a given path.
 */
import { redirect } from "next/navigation";
import { getClaims } from "@/lib/auth";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const claims = await getClaims();
  if (!claims) {
    redirect("/login");
  }

  return <div className="flex flex-1 flex-col">{children}</div>;
}
