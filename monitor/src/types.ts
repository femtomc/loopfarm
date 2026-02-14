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

