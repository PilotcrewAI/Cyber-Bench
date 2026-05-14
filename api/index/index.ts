import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
  bucketName,
  buildS3RunIndex,
  createS3Client,
  runsPrefixFromEnv,
} from "../../lib/transcript-viewer-s3-backend";

export default async function handler(
  req: VercelRequest,
  res: VercelResponse,
): Promise<void> {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  try {
    const client = createS3Client();
    const bucket = bucketName();
    const prefix = runsPrefixFromEnv();
    const bundles = await buildS3RunIndex(client, bucket, prefix);
    res.status(200).json({ bundles });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    res.status(500).json({ error: msg });
  }
}
