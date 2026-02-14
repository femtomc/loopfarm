import type { Store } from "./store";
import { renderEventsPage, renderIssuesPage } from "./html";
import { badRequest, htmlResponse, internalServerError, jsonResponse, methodNotAllowed, notFound } from "./responses";

function parseLimit(value: string | null, defaultLimit: number): number {
  if (!value) return defaultLimit;
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || n <= 0) return defaultLimit;
  return n;
}

export async function handleRequest(req: Request, ctx: { storeRoot: string; store: Store }): Promise<Response> {
  if (req.method !== "GET") return methodNotAllowed();

  const url = new URL(req.url);
  const pathname = decodeURIComponent(url.pathname);
  const parts = pathname.split("/").filter(Boolean);

  try {
    if (pathname === "/" || pathname === "/issues") {
      const issues = await ctx.store.listIssues();
      return htmlResponse(renderIssuesPage({ storeRoot: ctx.storeRoot, issues }));
    }

    if (pathname === "/events") {
      const issue_id = url.searchParams.get("issue_id")?.trim() || undefined;
      const run_id = url.searchParams.get("run_id")?.trim() || undefined;
      const type = url.searchParams.get("type")?.trim() || undefined;
      const limit = Math.min(parseLimit(url.searchParams.get("limit"), 200), 5000);

      const events = await ctx.store.queryEvents({ issue_id, run_id, type, limit });
      return htmlResponse(
        renderEventsPage({
          storeRoot: ctx.storeRoot,
          query: { issue_id, run_id, type, limit },
          events,
        }),
      );
    }

    if (pathname === "/api/issues") {
      const issues = await ctx.store.listIssues();
      return jsonResponse(issues);
    }

    if (parts[0] === "api" && parts[1] === "issues" && typeof parts[2] === "string") {
      const id = parts[2];

      if (parts.length === 3) {
        const issue = await ctx.store.getIssue(id);
        if (!issue) return notFound(`issue not found: ${id}`);
        return jsonResponse(issue);
      }

      if (parts.length === 4 && parts[3] === "children") {
        const children = await ctx.store.getIssueChildren(id);
        return jsonResponse(children);
      }
    }

    if (pathname === "/api/forum/topics") {
      const prefix = url.searchParams.get("prefix") ?? undefined;
      const limit = parseLimit(url.searchParams.get("limit"), 500);
      const topics = await ctx.store.listForumTopics({ prefix, limit });
      return jsonResponse(topics);
    }

    if (pathname === "/api/forum/messages") {
      const topic = url.searchParams.get("topic");
      if (!topic) return badRequest("missing required query param: topic");
      const limit = parseLimit(url.searchParams.get("limit"), 200);
      const messages = await ctx.store.listForumMessages({ topic, limit });
      return jsonResponse(messages);
    }

    if (pathname === "/api/events") {
      const issue_id = url.searchParams.get("issue_id")?.trim() || undefined;
      const run_id = url.searchParams.get("run_id")?.trim() || undefined;
      const type = url.searchParams.get("type")?.trim() || undefined;
      const limit = Math.min(parseLimit(url.searchParams.get("limit"), 200), 5000);
      const events = await ctx.store.queryEvents({ issue_id, run_id, type, limit });
      return jsonResponse(events);
    }

    return notFound("not found");
  } catch (err) {
    return internalServerError(err);
  }
}
