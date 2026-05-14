import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
  BadRequestError,
  NotFoundError,
  bucketName,
  createS3Client,
  loadRunFromS3,
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
  const bundle = req.query.bundle;
  const run = req.query.run;
  if (typeof bundle !== "string" || typeof run !== "string") {
    res.status(400).json({ error: "exactly one bundle= and run= query parameter required" });
    return;
  }
  try {
    const client = createS3Client();
    const bucket = bucketName();
    const prefix = runsPrefixFromEnv();
    const payload = await loadRunFromS3(client, bucket, prefix, bundle, run);
    res.status(200).json(payload);
  } catch (e: unknown) {
    if (e instanceof BadRequestError) {
      res.status(400).json({ error: e.message });
      return;
    }
    if (e instanceof NotFoundError) {
      res.status(404).json({ error: e.message });
      return;
    }
    const msg = e instanceof Error ? e.message : String(e);
    res.status(500).json({ error: msg });
  }
}
