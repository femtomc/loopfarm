import path from "node:path";
import fs from "node:fs/promises";
import type { EventRecord, ForumMessage, Issue, JsonRecord } from "./types";
import { parseJsonl } from "./jsonl";

const STORE_DIRNAME = ".inshallah";
const LOGS_DIRNAME = "logs";
const ENV_STORE_ROOT = "INSHALLAH_STORE_ROOT";

async function existsDir(p: string): Promise<boolean> {
  try {
    const st = await fs.stat(p);
    return st.isDirectory();
  } catch {
    return false;
  }
}

async function findAncestorWithStoreDir(startDir: string): Promise<string | null> {
  let dir = path.resolve(startDir);
  // Avoid infinite loops at filesystem root.
  for (;;) {
    if (await existsDir(path.join(dir, STORE_DIRNAME))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export async function discoverStoreRoot(opts?: {
  cwd?: string;
  env?: Record<string, string | undefined>;
}): Promise<string> {
  const cwd = opts?.cwd ?? process.cwd();
  const env = opts?.env ?? (process.env as Record<string, string | undefined>);

  const override = env[ENV_STORE_ROOT]?.trim();
  if (override) {
    const root = path.resolve(override);
    const storeDir = path.join(root, STORE_DIRNAME);
    if (!(await existsDir(storeDir))) {
      throw new Error(`${ENV_STORE_ROOT}=${root} but ${storeDir} does not exist`);
    }
    return root;
  }

  const found = await findAncestorWithStoreDir(cwd);
  if (!found) {
    throw new Error(`could not discover store root from cwd=${cwd} (no ancestor contains ${STORE_DIRNAME}/)`);
  }
  return found;
}

function expectRecord(value: unknown, ctx: string): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`expected object for ${ctx}`);
  }
  return value as JsonRecord;
}

function expectString(value: unknown, ctx: string): string {
  if (typeof value !== "string") throw new Error(`expected string for ${ctx}`);
  return value;
}

function asIssue(value: unknown): Issue {
  const obj = expectRecord(value, "issue");
  const id = expectString(obj.id, "issue.id");
  const title = typeof obj.title === "string" ? obj.title : "";
  return { ...obj, id, title } as Issue;
}

function asForumMessage(value: unknown): ForumMessage {
  const obj = expectRecord(value, "forum message");
  const topic = expectString(obj.topic, "forum.topic");
  const body = typeof obj.body === "string" ? obj.body : "";
  return { ...obj, topic, body } as ForumMessage;
}

function epochMsFromMessage(m: ForumMessage): number {
  if (typeof m.created_at_ms === "number" && Number.isFinite(m.created_at_ms)) return m.created_at_ms;
  if (typeof m.created_at === "number" && Number.isFinite(m.created_at)) return m.created_at * 1000;
  return 0;
}

class JsonlCache<T> {
  private cached: T[] | null = null;
  private mtimeMs: number | null = null;
  private size: number | null = null;

  constructor(
    private readonly filePath: string,
    private readonly coerce: (value: unknown) => T,
  ) {}

  async load(): Promise<T[]> {
    const st = await fs.stat(this.filePath);
    if (this.cached && this.mtimeMs === st.mtimeMs && this.size === st.size) return this.cached;

    const text = await Bun.file(this.filePath).text();
    const raw = parseJsonl(text, this.filePath);
    const out = raw.map(this.coerce);

    this.cached = out;
    this.mtimeMs = st.mtimeMs;
    this.size = st.size;
    return out;
  }
}

type LogFileInfo = {
  issue_id: string;
  variant: string;
  filePath: string;
  source: string;
  mtimeMs: number;
  size: number;
};

function parseLogFilename(filename: string): { issue_id: string; variant: string } | null {
  if (!filename.endsWith(".jsonl")) return null;
  const stem = filename.slice(0, -".jsonl".length);
  const idx = stem.indexOf(".");
  const issue_id = idx === -1 ? stem : stem.slice(0, idx);
  const variant = idx === -1 ? "" : stem.slice(idx + 1);
  if (!issue_id) return null;
  return { issue_id, variant };
}

function asEventRecord(
  value: unknown,
  meta: { issue_id: string; variant: string; source: string; line: number; run_id: string | null; parse_error?: string },
): EventRecord {
  const type =
    value && typeof value === "object" && !Array.isArray(value) && typeof (value as { type?: unknown }).type === "string"
      ? ((value as { type: string }).type ?? "json")
      : "json";

  return {
    issue_id: meta.issue_id,
    run_id: meta.run_id,
    type,
    variant: meta.variant,
    source: meta.source,
    line: meta.line,
    value,
    parse_error: meta.parse_error,
  };
}

function parseEventLog(text: string, meta: { issue_id: string; variant: string; source: string }): EventRecord[] {
  const out: EventRecord[] = [];
  const lines = text.split(/\r?\n/);
  let run_id: string | null = null;

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line) continue;

    const lineNo = i + 1;

    if (!line.startsWith("{")) {
      out.push(
        asEventRecord(raw, {
          ...meta,
          line: lineNo,
          run_id,
        }),
      );
      out[out.length - 1]!.type = "raw";
      continue;
    }

    try {
      const parsed = JSON.parse(line) as unknown;
      let evType: string | null = null;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const t = (parsed as { type?: unknown }).type;
        if (typeof t === "string") evType = t;
      }

      // `thread.started` establishes the run/thread id for subsequent events.
      if (evType === "thread.started") {
        const tid = (parsed as { thread_id?: unknown }).thread_id;
        if (typeof tid === "string") run_id = tid;
      }

      out.push(
        asEventRecord(parsed, {
          ...meta,
          line: lineNo,
          run_id,
        }),
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      out.push(
        asEventRecord(raw, {
          ...meta,
          line: lineNo,
          run_id,
          parse_error: msg,
        }),
      );
      out[out.length - 1]!.type = "raw";
    }
  }

  return out;
}

class EventLogCache {
  private cached: EventRecord[] | null = null;
  private mtimeMs: number | null = null;
  private size: number | null = null;

  constructor(
    private readonly filePath: string,
    private readonly meta: { issue_id: string; variant: string; source: string },
  ) {}

  async load(): Promise<EventRecord[]> {
    const st = await fs.stat(this.filePath);
    if (this.cached && this.mtimeMs === st.mtimeMs && this.size === st.size) return this.cached;

    const text = await Bun.file(this.filePath).text();
    const out = parseEventLog(text, this.meta);

    this.cached = out;
    this.mtimeMs = st.mtimeMs;
    this.size = st.size;
    return out;
  }
}

export class Store {
  readonly issuesPath: string;
  readonly forumPath: string;
  readonly logsDir: string;

  private readonly issuesCache: JsonlCache<Issue>;
  private readonly forumCache: JsonlCache<ForumMessage>;
  private readonly eventLogCaches: Map<string, EventLogCache> = new Map();

  constructor(readonly root: string) {
    this.issuesPath = path.join(root, STORE_DIRNAME, "issues.jsonl");
    this.forumPath = path.join(root, STORE_DIRNAME, "forum.jsonl");
    this.logsDir = path.join(root, STORE_DIRNAME, LOGS_DIRNAME);
    this.issuesCache = new JsonlCache(this.issuesPath, asIssue);
    this.forumCache = new JsonlCache(this.forumPath, asForumMessage);
  }

  async listIssues(): Promise<Issue[]> {
    const issues = await this.issuesCache.load();
    // Sort newest-first for a stable "monitor" feel.
    return [...issues].sort((a, b) => (b.updated_at ?? b.created_at ?? 0) - (a.updated_at ?? a.created_at ?? 0));
  }

  async getIssue(id: string): Promise<Issue | null> {
    const issues = await this.issuesCache.load();
    return issues.find((i) => i.id === id) ?? null;
  }

  async getIssueChildren(parentId: string): Promise<Issue[]> {
    const issues = await this.issuesCache.load();
    const children = issues.filter((i) => {
      const deps = i.deps;
      if (!Array.isArray(deps)) return false;
      return deps.some((d) => {
        if (!d || typeof d !== "object") return false;
        const dep = d as { type?: unknown; target?: unknown };
        return dep.type === "parent" && dep.target === parentId;
      });
    });
    return children.sort((a, b) => (b.updated_at ?? b.created_at ?? 0) - (a.updated_at ?? a.created_at ?? 0));
  }

  async listForumTopics(params?: { prefix?: string; limit?: number }): Promise<string[]> {
    const prefix = params?.prefix;
    const limit = params?.limit ?? 500;
    const messages = await this.forumCache.load();

    const newestByTopic = new Map<string, number>();
    for (const m of messages) {
      const topic = m.topic;
      if (prefix && !topic.startsWith(prefix)) continue;
      const ts = epochMsFromMessage(m);
      const prev = newestByTopic.get(topic);
      if (prev === undefined || ts > prev) newestByTopic.set(topic, ts);
    }

    const topics = [...newestByTopic.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([topic]) => topic);

    return topics.slice(0, limit);
  }

  async listForumMessages(params: { topic: string; limit?: number }): Promise<ForumMessage[]> {
    const limit = params.limit ?? 200;
    const messages = await this.forumCache.load();
    const topicMsgs = messages.filter((m) => m.topic === params.topic);
    topicMsgs.sort((a, b) => epochMsFromMessage(b) - epochMsFromMessage(a));
    return topicMsgs.slice(0, limit);
  }

  async listEventLogFiles(params?: { issue_id?: string }): Promise<LogFileInfo[]> {
    const issue_id = params?.issue_id;
    if (!(await existsDir(this.logsDir))) return [];

    const entries = await fs.readdir(this.logsDir, { withFileTypes: true });
    const out: LogFileInfo[] = [];

    for (const ent of entries) {
      if (!ent.isFile()) continue;
      const parsed = parseLogFilename(ent.name);
      if (!parsed) continue;
      if (issue_id && parsed.issue_id !== issue_id) continue;

      const filePath = path.join(this.logsDir, ent.name);
      const st = await fs.stat(filePath);
      out.push({
        issue_id: parsed.issue_id,
        variant: parsed.variant,
        filePath,
        source: ent.name,
        mtimeMs: st.mtimeMs,
        size: st.size,
      });
    }

    // Approximate chronological order.
    out.sort((a, b) => a.mtimeMs - b.mtimeMs || a.source.localeCompare(b.source));
    return out;
  }

  async queryEvents(params?: {
    issue_id?: string;
    run_id?: string;
    type?: string;
    limit?: number;
  }): Promise<EventRecord[]> {
    const issue_id = params?.issue_id;
    const run_id = params?.run_id;
    const type = params?.type;
    const limit = params?.limit ?? 200;

    const files = await this.listEventLogFiles({ issue_id });

    let events: EventRecord[] = [];
    for (const f of files) {
      let cache = this.eventLogCaches.get(f.filePath);
      if (!cache) {
        cache = new EventLogCache(f.filePath, {
          issue_id: f.issue_id,
          variant: f.variant,
          source: f.source,
        });
        this.eventLogCaches.set(f.filePath, cache);
      }
      events = events.concat(await cache.load());
    }

    if (run_id) events = events.filter((e) => e.run_id === run_id);
    if (type) events = events.filter((e) => e.type === type);

    // Default to a "tail" view while keeping chronological ordering.
    if (events.length > limit) events = events.slice(events.length - limit);
    return events;
  }
}
