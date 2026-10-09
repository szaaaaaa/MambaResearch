import { apiFetch } from './workbench';

export interface MetricSample {
  step: number;
  name: string;
  value: number;
  timestamp: number;
}

export interface RunStatus {
  run_id: string;
  status: string;
  exit_code: number | null;
  script_path: string;
  started_at: number;
  ended_at: number | null;
  elapsed_s: number | null;
  log_lines: number;
  metrics_count: number;
  last_metric: MetricSample | null;
}

export async function getExperimentSnapshot(runId: string): Promise<{ status: RunStatus; logs: string[]; metrics: MetricSample[] }> {
  const response = await apiFetch(`/api/experiments/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getExperimentRuns(): Promise<RunStatus[]> {
  const response = await apiFetch('/api/experiments');
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()).runs;
}
