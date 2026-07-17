/**
 * Per-client knowledge upload screen (S13.7). Reuses S13.3's `UploadForm`
 * as-is, parameterized by the route's `{tenantId}` (D1) so the upload and
 * status-poll actions target the S12.7 PLATFORM_ADMIN super-user surface
 * `/admin/tenants/{tenantId}/ingestion/**` instead of the implicit
 * `/admin/ingestion/**`.
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { UploadForm } from "@/app/(protected)/knowledge/upload-form";

export default async function ClientKnowledgePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>Upload knowledge</CardTitle>
          <CardDescription>
            Upload a .txt or .docx document (up to 10 MiB) for this client. It is parsed, chunked,
            and embedded asynchronously -- the panel below tracks the run&apos;s progress in real
            time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <UploadForm tenantId={tenantId} />
        </CardContent>
      </Card>
    </div>
  );
}
