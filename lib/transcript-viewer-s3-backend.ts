import {
  GetObjectCommand,
  ListObjectsV2Command,
  type ListObjectsV2CommandOutput,
  S3Client,
} from "@aws-sdk/client-s3";

const BENCHMARK_STATIC_JSON = "benchmark_static.json";

export class BadRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BadRequestError";
  }
}

export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}

export type BundleIndex = Record<string, string[]>;

export interface RunPayload {
  bundle: string;
  run: string;
  transcript: Record<string, unknown>[];
  result: Record<string, unknown> | null;
  transcript_path: string;
  opencode_path: string | null;
  result_path: string | null;
  benchmark_static_path: string | null;
  benchmark_context: Record<string, unknown>;
}

export function requireEnv(name: string): string {
  const v = process.env[name];
  if (v === undefined || v === "") {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return v;
}

export function createS3Client(): S3Client {
  const region = requireEnv("AWS_REGION");
  return new S3Client({ region });
}

/** Prefix such as "runs" or "runs/my-project" — keys are `${normPrefix}/${bundle}/${run}/transcript.jsonl` */
export function normalizedRunsPrefix(runsPrefix: string): string {
  const t = runsPrefix.trim().replace(/\/+$/, "");
  if (!t) {
    throw new Error("TRANSCRIPT_VIEWER_S3_PREFIX must not be empty");
  }
  return t;
}

export function bucketName(): string {
  return requireEnv("TRANSCRIPT_VIEWER_S3_BUCKET");
}

export function runsPrefixFromEnv(): string {
  const raw = process.env.TRANSCRIPT_VIEWER_S3_PREFIX ?? "runs";
  return normalizedRunsPrefix(raw);
}

function keyPrefix(runsPrefix: string): string {
  const n = normalizedRunsPrefix(runsPrefix);
  return `${n}/`;
}

export function isSafePathSegment(name: string): boolean {
  if (!name || name.length > 512) {
    return false;
  }
  if (name === "." || name === "..") {
    return false;
  }
  for (const bad of ["/", "\\", "\0"]) {
    if (name.includes(bad)) {
      return false;
    }
  }
  return true;
}

function parseTranscriptKey(objectKey: string, listPrefix: string): { bundle: string; run: string } | null {
  if (!objectKey.startsWith(listPrefix) || !objectKey.endsWith("/transcript.jsonl")) {
    return null;
  }
  const rest = objectKey.slice(listPrefix.length);
  const segments = rest.split("/").filter((s) => s.length > 0);
  if (segments.length !== 3 || segments[2] !== "transcript.jsonl") {
    return null;
  }
  const bundle = segments[0];
  const run = segments[1];
  return { bundle, run };
}

function isS3NotFound(err: unknown): boolean {
  if (typeof err !== "object" || err === null) {
    return false;
  }
  const o = err as { name?: string; Code?: string };
  const code = o.name ?? o.Code;
  return code === "NoSuchKey" || code === "NotFound";
}

async function getObjectUtf8(client: S3Client, bucket: string, key: string): Promise<string | null> {
  try {
    const out = await client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
    const body = out.Body;
    if (body === undefined) {
      return null;
    }
    return await body.transformToString("utf-8");
  } catch (e: unknown) {
    if (isS3NotFound(e)) {
      return null;
    }
    throw e;
  }
}

export async function buildS3RunIndex(
  client: S3Client,
  bucket: string,
  runsPrefix: string,
): Promise<BundleIndex> {
  const prefix = keyPrefix(runsPrefix);
  const bundles: Record<string, string[]> = {};
  let continuationToken: string | undefined;

  for (;;) {
    const resp: ListObjectsV2CommandOutput = await client.send(
      new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: prefix,
        ContinuationToken: continuationToken,
      }),
    );

    for (const obj of resp.Contents ?? []) {
      const key = obj.Key;
      if (key === undefined) {
        continue;
      }
      const parsed = parseTranscriptKey(key, prefix);
      if (parsed === null) {
        continue;
      }
      if (!isSafePathSegment(parsed.bundle) || !isSafePathSegment(parsed.run)) {
        continue;
      }
      const list = bundles[parsed.bundle] ?? [];
      if (!list.includes(parsed.run)) {
        list.push(parsed.run);
      }
      bundles[parsed.bundle] = list;
    }

    if (resp.IsTruncated !== true) {
      break;
    }
    continuationToken = resp.NextContinuationToken;
    if (continuationToken === undefined) {
      break;
    }
  }

  const sortedBundles: BundleIndex = {};
  for (const b of Object.keys(bundles).sort()) {
    const runs = bundles[b];
    runs.sort((a, c) => (a < c ? 1 : a > c ? -1 : 0));
    sortedBundles[b] = runs;
  }
  return sortedBundles;
}

function readJsonlLines(label: string, raw: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const lines = raw.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const s = lines[i]?.trim() ?? "";
    if (s === "") {
      continue;
    }
    let obj: unknown;
    try {
      obj = JSON.parse(s) as unknown;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(`${label}: invalid JSON on line ${i + 1}: ${msg}`);
    }
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
      throw new Error(`${label}: line ${i + 1} is not a JSON object`);
    }
    out.push(obj as Record<string, unknown>);
  }
  return out;
}

function readOpencodeLines(label: string, raw: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const lines = raw.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const s = lines[i]?.trim() ?? "";
    if (s === "") {
      continue;
    }
    let obj: unknown;
    try {
      obj = JSON.parse(s) as unknown;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(`${label}: invalid JSON on line ${i + 1}: ${msg}`);
    }
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
      throw new Error(`${label}: line ${i + 1} is not a JSON object`);
    }
    const row = obj as Record<string, unknown>;
    row._opencode_line = i + 1;
    out.push(row);
  }
  return out;
}

function mergeOpencodeTranscript(
  transcript: Record<string, unknown>[],
  opencode: Record<string, unknown>[],
): Record<string, unknown>[] {
  if (opencode.length === 0) {
    return transcript;
  }
  const normalized = normalizeOpencodeEvents(opencode);
  const prefix: Record<string, unknown>[] = [];
  const suffix: Record<string, unknown>[] = [];
  for (const event of transcript) {
    const ev = event.event;
    if (ev === "opencode_finish" || ev === "finish") {
      suffix.push(event);
    } else {
      prefix.push(event);
    }
  }
  return [...prefix, ...normalized, ...suffix];
}

function parseResultJson(label: string, raw: string): Record<string, unknown> {
  let data: unknown;
  try {
    data = JSON.parse(raw) as unknown;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`${label}: invalid JSON (${msg})`);
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error(`${label}: root must be an object`);
  }
  return data as Record<string, unknown>;
}

function firstTranscriptStart(raw: string): Record<string, unknown> | null {
  const lines = raw.split(/\r?\n/);
  for (const line of lines) {
    const s = line.trim();
    if (s === "") {
      continue;
    }
    let obj: unknown;
    try {
      obj = JSON.parse(s) as unknown;
    } catch {
      continue;
    }
    if (typeof obj === "object" && obj !== null && !Array.isArray(obj)) {
      const o = obj as Record<string, unknown>;
      if (o.event === "start") {
        return o;
      }
    }
  }
  return null;
}

function benchmarkMetaFromRun(
  transcriptRaw: string,
  resultRaw: string | null,
): { bundle_id: string; level: number | null; backend: string | null; manifest_path: string } {
  let bundleId = "";
  let level: number | null = null;
  let backend: string | null = null;

  if (resultRaw !== null) {
    try {
      const parsed = parseResultJson("result.json", resultRaw);
      const bid = parsed.bundle_id;
      bundleId = typeof bid === "string" ? bid : "";
      const br = parsed.backend;
      if (typeof br === "string" && br.length > 0) {
        backend = br;
      }
    } catch {
      /* treat as missing */
    }
  }

  const startEv = firstTranscriptStart(transcriptRaw);
  if (startEv !== null) {
    if (bundleId === "") {
      const bid = startEv.bundle_id;
      bundleId = typeof bid === "string" ? bid : "";
    }
    const lv = startEv.level;
    if (lv !== undefined && lv !== null) {
      const n = typeof lv === "number" ? lv : Number(lv);
      level = Number.isFinite(n) ? Math.trunc(n) : null;
    }
    if (backend === null || backend === "") {
      const sb = startEv.backend;
      if (typeof sb === "string" && sb.length > 0) {
        backend = sb;
      }
    }
  }

  return { bundle_id: bundleId, level, backend, manifest_path: "" };
}

function displayPath(runsPrefix: string, bundle: string, run: string, ...parts: string[]): string {
  const base = normalizedRunsPrefix(runsPrefix);
  const tail = [bundle, run, ...parts].join("/");
  return `${base}/${tail}`;
}

function isSubmitFlagCommand(command: string): boolean {
  const tokens = command.split(/\s+/);
  return tokens.includes("submit_flag") || command.includes("./submit_flag");
}

function extractFlagFromCommand(command: string): string {
  for (const prefix of ["CYBERBENCH{", "CTF{"]) {
    const start = command.indexOf(prefix);
    if (start >= 0) {
      const end = command.indexOf("}", start);
      if (end >= 0) {
        return command.slice(start, end + 1);
      }
    }
  }
  return "";
}

function opencodeSubmitResult(output: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(output) as unknown;
  } catch {
    return {};
  }
  if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
    return parsed as Record<string, unknown>;
  }
  return {};
}

function opencodeElapsedSeconds(state: Record<string, unknown>): number | null {
  const timeData = state.time;
  if (typeof timeData !== "object" || timeData === null || Array.isArray(timeData)) {
    return null;
  }
  const td = timeData as Record<string, unknown>;
  const start = td.start;
  const end = td.end;
  if (
    (typeof start === "number" || typeof start === "bigint") &&
    (typeof end === "number" || typeof end === "bigint")
  ) {
    const s = Number(start);
    const e = Number(end);
    if (e >= s) {
      return (e - s) / 1000;
    }
  }
  return null;
}

function opencodeShellResult(
  state: Record<string, unknown>,
  metadata: Record<string, unknown>,
): Record<string, unknown> {
  const out = String(state.output ?? metadata.output ?? "");
  let exitCode: number | null = null;
  const exitRaw = metadata.exit;
  if (exitRaw !== undefined && exitRaw !== null) {
    const n = Number(metadata.exit);
    exitCode = Number.isFinite(n) ? Math.trunc(n) : null;
  }
  const status = state.status;
  return {
    ok: status === "completed" && (exitCode === null || exitCode === 0),
    exit_code: exitCode,
    stdout: out,
    stderr: "",
    timed_out: status === "timed_out",
    elapsed_seconds: opencodeElapsedSeconds(state),
  };
}

function normalizeOpencodeToolUse(
  part: Record<string, unknown>,
  step: number,
  lineNo: unknown,
): Record<string, unknown>[] {
  let state = part.state;
  if (typeof state !== "object" || state === null || Array.isArray(state)) {
    state = {};
  }
  const st = state as Record<string, unknown>;
  let toolInput = st.input;
  if (typeof toolInput !== "object" || toolInput === null || Array.isArray(toolInput)) {
    toolInput = {};
  }
  const ti = toolInput as Record<string, unknown>;
  let metadata = st.metadata;
  if (typeof metadata !== "object" || metadata === null || Array.isArray(metadata)) {
    metadata = {};
  }
  const md = metadata as Record<string, unknown>;
  const rawCall = part.callID ?? part.id;
  const callId =
    typeof rawCall === "string" || typeof rawCall === "number"
      ? String(rawCall)
      : `opencode-${String(lineNo)}`;

  const cmd = String(ti.command ?? "");
  const toolName = isSubmitFlagCommand(cmd) ? "submit_flag" : String(part.tool ?? "tool");
  let arguments_: Record<string, unknown>;
  let result: Record<string, unknown>;
  if (toolName === "submit_flag") {
    arguments_ = { flag: extractFlagFromCommand(cmd), command: cmd };
    result = opencodeSubmitResult(String(st.output ?? md.output ?? ""));
  } else {
    arguments_ = { command: cmd, description: ti.description };
    result = opencodeShellResult(st, md);
  }

  const assistant: Record<string, unknown> = {
    event: "assistant",
    source: "opencode",
    step,
    message: {
      role: "assistant",
      tool_calls: [
        {
          id: callId,
          function: {
            name: toolName,
            arguments: JSON.stringify(arguments_),
          },
        },
      ],
    },
    opencode_line: lineNo,
  };
  const toolResult: Record<string, unknown> = {
    event: "tool_result",
    source: "opencode",
    step,
    tool_call_id: callId,
    result,
    opencode_line: lineNo,
  };
  return [assistant, toolResult];
}

function normalizeOpencodeEvents(events: Record<string, unknown>[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  let step = 0;
  for (const event of events) {
    const eventType = event.type;
    const part = event.part;
    if (typeof part !== "object" || part === null || Array.isArray(part)) {
      continue;
    }
    const p = part as Record<string, unknown>;
    if (eventType === "step_start") {
      step += 1;
      continue;
    }
    if (eventType === "text") {
      const text = p.text;
      if (typeof text === "string" && text.length > 0) {
        out.push({
          event: "assistant",
          source: "opencode",
          step,
          message: { role: "assistant", content: text },
          opencode_line: event._opencode_line,
        });
      }
      continue;
    }
    if (eventType === "tool_use") {
      out.push(...normalizeOpencodeToolUse(p, step, event._opencode_line));
      continue;
    }
    if (eventType === "step_finish") {
      out.push({
        event: "opencode_step_finish",
        source: "opencode",
        step,
        reason: p.reason,
        cost: p.cost,
        tokens: p.tokens,
        opencode_line: event._opencode_line,
      });
    }
  }
  return out;
}

async function loadBenchmarkContext(
  client: S3Client,
  bucket: string,
  runsPrefix: string,
  bundle: string,
  run: string,
  transcriptRaw: string,
  resultRaw: string | null,
): Promise<Record<string, unknown>> {
  const base = keyPrefix(runsPrefix);
  const snapKey = `${base}${bundle}/${run}/${BENCHMARK_STATIC_JSON}`;
  const snapRaw = await getObjectUtf8(client, bucket, snapKey);
  if (snapRaw !== null) {
    let raw: unknown;
    try {
      raw = JSON.parse(snapRaw) as unknown;
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : String(exc);
      const meta = benchmarkMetaFromRun(transcriptRaw, resultRaw);
      return {
        source: "invalid_snapshot",
        file_path: displayPath(runsPrefix, bundle, run, BENCHMARK_STATIC_JSON),
        notice: `benchmark_static.json is not valid JSON (${msg}).`,
        sections: [],
        ...meta,
      };
    }
    if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
      const obj = raw as Record<string, unknown>;
      const sections = obj.sections;
      if (Array.isArray(sections)) {
        return {
          ...obj,
          source: "snapshot",
          file_path: displayPath(runsPrefix, bundle, run, BENCHMARK_STATIC_JSON),
        };
      }
    }
  }

  const targetsKey = `${base}${bundle}/${run}/workspace/TARGETS.md`;
  const agentKey = `${base}${bundle}/${run}/workspace/.opencode/agent/cyberbench.md`;
  const targetsRaw = await getObjectUtf8(client, bucket, targetsKey);
  const agentRaw = await getObjectUtf8(client, bucket, agentKey);
  if (targetsRaw !== null || agentRaw !== null) {
    const sections: Record<string, unknown>[] = [];
    if (agentRaw !== null) {
      sections.push({
        id: "agent_config",
        title: "Agent instructions (.opencode/agent/cyberbench.md)",
        content: agentRaw,
      });
    }
    if (targetsRaw !== null) {
      sections.push({
        id: "targets",
        title: "Targets (TARGETS.md)",
        content: targetsRaw,
      });
    }
    const meta = benchmarkMetaFromRun(transcriptRaw, resultRaw);
    return {
      version: 1,
      backend: String(meta.backend ?? "opencode"),
      bundle_id: String(meta.bundle_id ?? ""),
      level: meta.level,
      manifest_path: "",
      source: "workspace",
      file_path: null,
      notice:
        "Reconstructed from workspace files on disk (benchmark_static.json missing). CLI prompt and manifest path are omitted.",
      sections,
    };
  }

  const meta = benchmarkMetaFromRun(transcriptRaw, resultRaw);
  return {
    version: 1,
    bundle_id: String(meta.bundle_id ?? ""),
    level: meta.level,
    backend: meta.backend,
    manifest_path: "",
    source: "missing",
    file_path: null,
    sections: [],
    notice:
      "No benchmark_static.json and no workspace/TARGETS.md found. Re-run with an up-to-date cyberbench to emit benchmark_static.json.",
  };
}

export async function loadRunFromS3(
  client: S3Client,
  bucket: string,
  runsPrefix: string,
  bundle: string,
  run: string,
): Promise<RunPayload> {
  if (!isSafePathSegment(bundle) || !isSafePathSegment(run)) {
    throw new BadRequestError("invalid bundle or run name");
  }

  const base = keyPrefix(runsPrefix);
  const transcriptKey = `${base}${bundle}/${run}/transcript.jsonl`;
  const transcriptRaw = await getObjectUtf8(client, bucket, transcriptKey);
  if (transcriptRaw === null) {
    throw new NotFoundError("transcript.jsonl not found");
  }

  const transcript = readJsonlLines("transcript.jsonl", transcriptRaw);
  const opencodeKey = `${base}${bundle}/${run}/opencode.stdout.jsonl`;
  const opencodeRaw = await getObjectUtf8(client, bucket, opencodeKey);
  const opencode =
    opencodeRaw === null ? [] : readOpencodeLines("opencode.stdout.jsonl", opencodeRaw);
  const merged = mergeOpencodeTranscript(transcript, opencode);

  const resultKey = `${base}${bundle}/${run}/result.json`;
  const resultRaw = await getObjectUtf8(client, bucket, resultKey);
  let resultObj: Record<string, unknown> | null = null;
  if (resultRaw !== null) {
    resultObj = parseResultJson("result.json", resultRaw);
  }

  const transcriptPath = displayPath(runsPrefix, bundle, run, "transcript.jsonl");
  const opencodePath =
    opencodeRaw !== null ? displayPath(runsPrefix, bundle, run, "opencode.stdout.jsonl") : null;
  const resultPath =
    resultRaw !== null ? displayPath(runsPrefix, bundle, run, "result.json") : null;
  const staticKey = `${base}${bundle}/${run}/${BENCHMARK_STATIC_JSON}`;
  const staticRaw = await getObjectUtf8(client, bucket, staticKey);
  const benchmarkStaticPath =
    staticRaw !== null ? displayPath(runsPrefix, bundle, run, BENCHMARK_STATIC_JSON) : null;

  const benchmarkContext = await loadBenchmarkContext(
    client,
    bucket,
    runsPrefix,
    bundle,
    run,
    transcriptRaw,
    resultRaw,
  );

  return {
    bundle,
    run,
    transcript: merged,
    result: resultObj,
    transcript_path: transcriptPath,
    opencode_path: opencodePath,
    result_path: resultPath,
    benchmark_static_path: benchmarkStaticPath,
    benchmark_context: benchmarkContext,
  };
}
