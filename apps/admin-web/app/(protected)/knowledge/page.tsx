/**
 * Knowledge upload screen (S13.3). CLIENT_ADMIN-only -- gated by
 * `requireRole` (decision 2), colocated with this screen rather than a
 * `proxy.ts` route->role map, matching the S13.2 pattern. This intentionally
 * excludes both PLATFORM_ADMIN and CLIENT_AGENT: the backend's
 * `require_roles(Role.CLIENT_ADMIN)` (routes.py:49) is an exact allowlist,
 * not hierarchical.
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
import { UploadForm } from "@/app/(protected)/knowledge/upload-form";

export default async function KnowledgePage() {
  await requireRole("CLIENT_ADMIN");

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <div className="w-full max-w-xl">
        <Link href="/" className="text-sm text-muted-foreground hover:underline">
          ← Back to console
        </Link>
      </div>
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>Upload knowledge</CardTitle>
          <CardDescription>
            Upload a .txt or .docx document (up to 10 MiB). It is parsed, chunked, and embedded
            asynchronously -- the panel below tracks the run&apos;s progress in real time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <UploadForm />
        </CardContent>
      </Card>
    </div>
  );
}
