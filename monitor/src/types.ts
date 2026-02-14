export type JsonRecord = Record<string, unknown>;

export type IssueDep = {
  type: string;
  target: string;
} & JsonRecord;

export type Issue = {
  id: string;
  title: string;
  body?: string;
  status?: string;
  outcome?: string | null;
  tags?: string[];
  deps?: IssueDep[];
  execution_spec?: unknown;
  priority?: number;
  created_at?: number;
  updated_at?: number;
} & JsonRecord;

export type ForumMessage = {
  topic: string;
  body: string;
  author?: string;
  created_at?: number;
  created_at_ms?: number;
  id?: string;
  source?: string;
} & JsonRecord;

// Parsed entry from `.inshallah/logs/*.jsonl`.
//
// Notes:
// - `issue_id` is derived from the log filename.
// - `run_id` is derived from the most recent `thread.started` event in that file (if any).
// - `value` is either the parsed JSON object (for JSON lines) or the raw line string.
export type EventRecord = {
  issue_id: string;
  run_id: string | null;
  type: string;
  variant: string;
  source: string;
  line: number;
  value: unknown;
  parse_error?: string;
};
