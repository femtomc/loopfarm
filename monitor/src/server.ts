import { discoverStoreRoot, Store } from "./store";
import { handleRequest } from "./router";
import { textResponse } from "./responses";

function parsePort(value: string | undefined, defaultPort: number): number {
  if (!value) return defaultPort;
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || n <= 0) return defaultPort;
  return n;
}

const host = process.env.HOST ?? "127.0.0.1";
const port = parsePort(process.env.PORT, 3000);

const storeRoot = await discoverStoreRoot();
const store = new Store(storeRoot);

const server = Bun.serve({
  hostname: host,
  port,
  fetch: (req) => handleRequest(req, { storeRoot, store }),
  error: (err) => {
    // Bun calls this on thrown errors from fetch; keep response small.
    return textResponse(err instanceof Error ? err.message : String(err), { status: 500 });
  },
});

// eslint-disable-next-line no-console
console.log(`[inshallah-monitor] store_root=${storeRoot}`);
// eslint-disable-next-line no-console
console.log(`[inshallah-monitor] listening http://${server.hostname}:${server.port}`);

