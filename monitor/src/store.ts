import path from "node:path";
import fs from "node:fs/promises";
import type { ForumMessage, Issue, JsonRecord } from "./types";
import { parseJsonl } from "./jsonl";

const STORE_DIRNAME = ".inshallah";
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

export class Store {
  readonly issuesPath: string;
  readonly forumPath: string;

  private readonly issuesCache: JsonlCache<Issue>;
  private readonly forumCache: JsonlCache<ForumMessage>;

  constructor(readonly root: string) {
    this.issuesPath = path.join(root, STORE_DIRNAME, "issues.jsonl");
    this.forumPath = path.join(root, STORE_DIRNAME, "forum.jsonl");
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
}

