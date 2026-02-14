import { describe, expect, test } from "bun:test";
import path from "node:path";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { discoverStoreRoot, Store } from "../src/store";

async function makeStoreRoot(): Promise<string> {
  const root = await mkdtemp(path.join(tmpdir(), "inshallah-monitor-"));
  await mkdir(path.join(root, ".inshallah"));
  await writeFile(path.join(root, ".inshallah/issues.jsonl"), "");
  await writeFile(path.join(root, ".inshallah/forum.jsonl"), "");
  return root;
}

describe("store discovery", () => {
  test("discovers store root via env override", async () => {
    const root = await makeStoreRoot();
    const found = await discoverStoreRoot({
      cwd: path.join(root, "nested", "dir"),
      env: { INSHALLAH_STORE_ROOT: root },
    });
    expect(found).toBe(root);
  });

  test("discovers store root by walking ancestors", async () => {
    const root = await makeStoreRoot();
    const nested = path.join(root, "a", "b", "c");
    await mkdir(nested, { recursive: true });
    const found = await discoverStoreRoot({ cwd: nested, env: {} });
    expect(found).toBe(root);
  });
});

describe("issue helpers", () => {
  test("computes children via parent deps", async () => {
    const root = await makeStoreRoot();
    const issuesPath = path.join(root, ".inshallah/issues.jsonl");
    await writeFile(
      issuesPath,
      [
        JSON.stringify({ id: "p", title: "parent", deps: [], created_at: 1, updated_at: 1 }),
        JSON.stringify({
          id: "c1",
          title: "child 1",
          deps: [{ type: "parent", target: "p" }],
          created_at: 2,
          updated_at: 2,
        }),
        JSON.stringify({ id: "x", title: "other", deps: [], created_at: 3, updated_at: 3 }),
        JSON.stringify({
          id: "c2",
          title: "child 2",
          deps: [{ type: "parent", target: "p" }],
          created_at: 4,
          updated_at: 4,
        }),
        "",
      ].join("\n"),
    );

    const store = new Store(root);
    const children = await store.getIssueChildren("p");
    expect(children.map((c) => c.id)).toEqual(["c2", "c1"]);
  });
});

describe("forum helpers", () => {
  test("lists topics with optional prefix, newest-first", async () => {
    const root = await makeStoreRoot();
    const forumPath = path.join(root, ".inshallah/forum.jsonl");
    await writeFile(
      forumPath,
      [
        JSON.stringify({ topic: "issue:p", body: "a", author: "u", created_at: 1 }),
        JSON.stringify({ topic: "issue:p", body: "b", author: "u", created_at: 2 }),
        JSON.stringify({ topic: "research:x", body: "c", author: "u", created_at: 3 }),
        "",
      ].join("\n"),
    );

    const store = new Store(root);
    expect(await store.listForumTopics()).toEqual(["research:x", "issue:p"]);
    expect(await store.listForumTopics({ prefix: "issue:" })).toEqual(["issue:p"]);
  });

  test("lists messages by topic with limit, newest-first", async () => {
    const root = await makeStoreRoot();
    const forumPath = path.join(root, ".inshallah/forum.jsonl");
    await writeFile(
      forumPath,
      [
        JSON.stringify({ topic: "issue:p", body: "a", author: "u", created_at: 1 }),
        JSON.stringify({ topic: "issue:p", body: "b", author: "u", created_at: 2 }),
        JSON.stringify({ topic: "issue:p", body: "c", author: "u", created_at: 3 }),
        "",
      ].join("\n"),
    );

    const store = new Store(root);
    const msgs = await store.listForumMessages({ topic: "issue:p", limit: 2 });
    expect(msgs.map((m) => m.body)).toEqual(["c", "b"]);
  });
});

