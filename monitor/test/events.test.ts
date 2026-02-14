import { describe, expect, test } from "bun:test";
import path from "node:path";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { handleRequest } from "../src/router";
import { Store } from "../src/store";

async function makeStoreRootWithLogs(): Promise<string> {
  const root = await mkdtemp(path.join(tmpdir(), "inshallah-monitor-events-"));
  await mkdir(path.join(root, ".inshallah", "logs"), { recursive: true });
  await writeFile(path.join(root, ".inshallah/issues.jsonl"), "");
  await writeFile(path.join(root, ".inshallah/forum.jsonl"), "");
  return root;
}

async function writeLog(root: string, name: string, lines: string[]): Promise<void> {
  await writeFile(path.join(root, ".inshallah", "logs", name), lines.join("\n") + "\n");
}

describe("event logs", () => {
  test("parses event logs and derives issue_id/run_id", async () => {
    const root = await makeStoreRootWithLogs();

    await writeLog(root, "inshallah-aaa11111.jsonl", [
      JSON.stringify({ type: "thread.started", thread_id: "run-a-1" }),
      JSON.stringify({ type: "turn.started" }),
      "2026-02-14T00:00:00Z ERROR something happened",
      JSON.stringify({ type: "item.started", item: { id: "i1", type: "command_execution", command: "echo hi" } }),
      JSON.stringify({ type: "item.completed", item: { id: "i1", type: "command_execution", exit_code: 0 } }),
      JSON.stringify({ type: "thread.started", thread_id: "run-a-2" }),
      JSON.stringify({ type: "item.completed", item: { id: "i2", type: "agent_message", text: "hello" } }),
    ]);

    await writeLog(root, "inshallah-aaa11111.review.jsonl", [
      JSON.stringify({ type: "thread.started", thread_id: "run-a-review" }),
      JSON.stringify({ type: "item.completed", item: { id: "i3", type: "reasoning", text: "ok" } }),
    ]);

    await writeLog(root, "inshallah-bbb22222.jsonl", [
      JSON.stringify({ type: "thread.started", thread_id: "run-b-1" }),
      JSON.stringify({ type: "item.completed", item: { id: "b1", type: "agent_message", text: "bbb" } }),
    ]);

    const store = new Store(root);
    const events = await store.queryEvents({ issue_id: "inshallah-aaa11111", limit: 1000 });

    expect(events.length).toBe(9);
    expect(new Set(events.map((e) => e.issue_id))).toEqual(new Set(["inshallah-aaa11111"]));

    // run_id is derived from the most recent thread.started event in each log file.
    expect(events[0]!.type).toBe("thread.started");
    expect(events[0]!.run_id).toBe("run-a-1");
    expect(events[1]!.type).toBe("turn.started");
    expect(events[1]!.run_id).toBe("run-a-1");

    const raw = events.find((e) => e.type === "raw");
    expect(raw).toBeTruthy();
    expect(raw!.run_id).toBe("run-a-1");
    expect(typeof raw!.value).toBe("string");

    const run2 = events.find((e) => e.run_id === "run-a-2" && e.type === "thread.started");
    expect(run2).toBeTruthy();

    const review = events.find((e) => e.run_id === "run-a-review" && e.type === "thread.started");
    expect(review).toBeTruthy();
  });

  test("supports filtering by issue_id, run_id, type, and limit (tail)", async () => {
    const root = await makeStoreRootWithLogs();
    await writeLog(root, "inshallah-aaa11111.jsonl", [
      JSON.stringify({ type: "thread.started", thread_id: "run-a-1" }),
      JSON.stringify({ type: "turn.started" }),
      JSON.stringify({ type: "item.completed", item: { id: "i1", type: "agent_message", text: "hello" } }),
      JSON.stringify({ type: "thread.started", thread_id: "run-a-2" }),
      JSON.stringify({ type: "item.completed", item: { id: "i2", type: "agent_message", text: "bye" } }),
    ]);

    const store = new Store(root);

    const run1 = await store.queryEvents({ issue_id: "inshallah-aaa11111", run_id: "run-a-1", limit: 1000 });
    expect(run1.map((e) => e.run_id)).toEqual(["run-a-1", "run-a-1", "run-a-1"]);

    const threads = await store.queryEvents({ issue_id: "inshallah-aaa11111", type: "thread.started", limit: 1000 });
    expect(threads.map((e) => e.run_id)).toEqual(["run-a-1", "run-a-2"]);

    const tail = await store.queryEvents({ issue_id: "inshallah-aaa11111", limit: 2 });
    expect(tail.map((e) => e.type)).toEqual(["thread.started", "item.completed"]);
    expect(tail.map((e) => e.run_id)).toEqual(["run-a-2", "run-a-2"]);
  });

  test("exposes /api/events with filters", async () => {
    const root = await makeStoreRootWithLogs();
    await writeLog(root, "inshallah-aaa11111.jsonl", [
      JSON.stringify({ type: "thread.started", thread_id: "run-a-1" }),
      JSON.stringify({ type: "turn.started" }),
      JSON.stringify({ type: "thread.started", thread_id: "run-a-2" }),
    ]);

    const store = new Store(root);
    const res = await handleRequest(
      new Request("http://example.test/api/events?issue_id=inshallah-aaa11111&type=thread.started&limit=10"),
      { storeRoot: root, store },
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as Array<{ type: string; run_id: string | null }>;
    expect(body.map((e) => e.type)).toEqual(["thread.started", "thread.started"]);
    expect(body.map((e) => e.run_id)).toEqual(["run-a-1", "run-a-2"]);
  });
});

