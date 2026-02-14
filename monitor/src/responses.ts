export function jsonResponse(value: unknown, init?: ResponseInit): Response {
  return Response.json(value, init);
}

export function htmlResponse(html: string, init?: ResponseInit): Response {
  return new Response(html, {
    ...init,
    headers: {
      "content-type": "text/html; charset=utf-8",
      ...(init?.headers ?? {}),
    },
  });
}

export function textResponse(text: string, init?: ResponseInit): Response {
  return new Response(text, {
    ...init,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      ...(init?.headers ?? {}),
    },
  });
}

export function badRequest(message: string): Response {
  return jsonResponse({ error: message }, { status: 400 });
}

export function notFound(message: string): Response {
  return jsonResponse({ error: message }, { status: 404 });
}

export function methodNotAllowed(): Response {
  return jsonResponse({ error: "method not allowed" }, { status: 405 });
}

export function internalServerError(err: unknown): Response {
  const msg = err instanceof Error ? err.stack ?? err.message : String(err);
  return jsonResponse({ error: "internal server error", detail: msg }, { status: 500 });
}

