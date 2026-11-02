import { NextResponse } from "next/server";
import { getSessionUser } from "@/lib/supabase/server";

export const runtime = "nodejs";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_CONTENT_TYPES = new Set([
  "chemical/x-pdb",
  "chemical/x-cif",
  "application/octet-stream",
]);

function isAllowedUploadUrl(raw: string): boolean {
  let candidate: URL;
  try {
    candidate = new URL(raw);
  } catch {
    return false;
  }

  if (candidate.username || candidate.password) return false;

  const explicitEndpoint = process.env.R2_ENDPOINT;
  if (explicitEndpoint) {
    try {
      const endpoint = new URL(explicitEndpoint);
      if (candidate.origin === endpoint.origin) return true;
    } catch {
      // Ignore malformed optional configuration and validate against the
      // account-scoped Cloudflare hostname below.
    }
  }

  const accountId = process.env.R2_ACCOUNT_ID?.trim();
  if (!accountId || candidate.protocol !== "https:" || candidate.port) {
    return false;
  }

  const accountHost = `${accountId}.r2.cloudflarestorage.com`;
  const isAccountHost =
    candidate.hostname === accountHost ||
    candidate.hostname.endsWith(`.${accountHost}`);
  const hasSignature =
    candidate.searchParams.has("X-Amz-Signature") ||
    candidate.searchParams.has("x-amz-signature");

  return isAccountHost && hasSignature;
}

export async function POST(request: Request): Promise<Response> {
  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json({ error: "invalid multipart body" }, { status: 400 });
  }

  const rawUrl = form.get("uploadUrl");
  const file = form.get("file");
  const rawContentType = form.get("contentType");

  if (typeof rawUrl !== "string" || !isAllowedUploadUrl(rawUrl)) {
    return NextResponse.json({ error: "invalid upload destination" }, { status: 400 });
  }
  if (!(file instanceof Blob) || file.size <= 0) {
    return NextResponse.json({ error: "missing upload file" }, { status: 400 });
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: "upload exceeds 10 MB" }, { status: 413 });
  }

  const contentType =
    typeof rawContentType === "string" &&
    ALLOWED_CONTENT_TYPES.has(rawContentType)
      ? rawContentType
      : "chemical/x-pdb";

  let upstream: Response;
  try {
    upstream = await fetch(rawUrl, {
      method: "PUT",
      headers: {
        "content-type": contentType,
        "content-length": String(file.size),
      },
      body: file,
    });
  } catch {
    return NextResponse.json(
      { error: "workspace storage is temporarily unreachable" },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const detail = await upstream.text().catch(() => "");
    console.error(
      `[uploads/presigned] R2 rejected upload (${upstream.status}): ${detail.slice(0, 200)}`,
    );
    return NextResponse.json(
      { error: "workspace storage rejected the upload" },
      { status: 502 },
    );
  }

  return new Response(null, { status: 204 });
}
