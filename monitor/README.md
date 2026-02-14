# Inshallah Monitor (Bun + TypeScript)

Small read-only monitor server for an `.inshallah/` JSONL store.

## Run

```bash
cd inshallah/monitor

# optional override (defaults to nearest ancestor of cwd containing .inshallah/)
export INSHALLAH_STORE_ROOT="$PWD/../.."

bun install
bun run dev
```

Env:
- `INSHALLAH_STORE_ROOT`: directory that contains `.inshallah/`
- `PORT`: server port (default `3000`)
- `HOST`: bind host (default `127.0.0.1`)

## Routes

HTML:
- `GET /` (issues list)

JSON:
- `GET /api/issues`
- `GET /api/issues/:id`
- `GET /api/issues/:id/children`
- `GET /api/forum/topics?prefix=...&limit=...`
- `GET /api/forum/messages?topic=...&limit=...`

