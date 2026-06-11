// Shared API helpers. The backend streams Server-Sent Events; we parse the
// `data:` lines and invoke a callback per event.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type FeedEvent =
  | { kind: "start"; theme: string; age: number; rerun?: boolean }
  | {
      kind: "node";
      node: string;
      label: string;
      action: string;
      detail: {
        preview?: string;
        decision?: string;
        critique?: string;
        rows?: number;
        completed?: { filename: string; url: string; object_name: string }[];
        metrics?: NodeMetrics;
        quota_exhausted?: boolean;
        pending_count?: number;
        quota_wait?: boolean;
      };
    }
  | {
      kind: "questions_ready";
      blueprint: string;
      matrix: any[];
    }
  | {
      kind: "complete";
      theme: string;
      age: number;
      blueprint: string;
      matrix: any[];
      images: { filename: string; url: string; object_name: string }[];
      failed: string[];
      history: string[];
      eval?: EvalResult;
      metrics?: RunMetrics;
      pending_images?: any[];
      play_url?: string;
      s3_uri?: string;
    };

// ── Metrics types ──

export interface NodeMetrics {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  model: string;
}

export interface PerNodeSummary {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  cost: number;
  model: string;
}

export interface RunMetrics {
  total_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
  total_llm_calls: number;
  total_image_calls: number;
  retries: Record<string, number>;
  llm_calls: {
    node: string;
    role: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
    cost: number;
  }[];
  node_timings: { node: string; latency_ms: number }[];
  per_node_summary: Record<string, PerNodeSummary>;
}

// ── Eval types ──

export interface EvalDimension {
  name: string;
  score: number;
  weight: number;
  lane: string;        // "deterministic" | "llm" | "heuristic"
  passed: number;
  total: number;
  issues: string[];
  detail: string;
}

export interface EvalResult {
  case_id: string;
  theme: string;
  age: number;
  total_score: number;
  grade: string;
  row_count: number;
  llm_calls: number;
  dimensions: EvalDimension[];
  error?: string;
}

// POST a JSON body and stream back SSE events, calling onEvent for each.
export async function streamPost(
  path: string,
  body: any,
  onEvent: (e: FeedEvent) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.body) throw new Error("No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let nl;
    while ((nl = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 2);
      if (chunk.startsWith("data:")) {
        try {
          onEvent(JSON.parse(chunk.slice(5).trim()));
        } catch {
          /* ignore malformed */
        }
      }
    }
  }
}

// Resolve a possibly-relative image URL (local storage) against the API base.
export function imageUrl(url: string): string {
  if (url.startsWith("http")) return url;
  return `${API_BASE}${url}`;
}

export interface RunRecord {
  id: string;
  timestamp: string;
  theme: string;
  age: number;
  milestone_code?: string;
  theme_code?: string;
  blueprint: string;
  matrix: any[];
  images: { filename: string; url: string; object_name: string }[];
  failed: string[];
  history: string[];
  eval?: EvalResult;
  metrics?: RunMetrics;
  pending_images?: any[];
  feed?: { node: string; label: string; action: string; detail: any }[];
  play_url?: string;
  s3_uri?: string;
}

export async function retryImages(
  runId: string,
  onEvent: (e: FeedEvent) => void
): Promise<void> {
  return streamPost(`/api/retry-images/${runId}`, {}, onEvent);
}

export async function fetchRuns(): Promise<RunRecord[]> {
  const res = await fetch(`${API_BASE}/api/runs`);
  if (!res.ok) return [];
  return res.json();
}

export interface RunMode {
  trial_mode: boolean;
  max_questions: number;
  max_images: number;
}

export async function fetchRunMode(): Promise<RunMode | null> {
  try {
    const res = await fetch(`${API_BASE}/api/run-mode`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
