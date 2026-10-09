import { apiFetch } from './workbench';

export interface CapabilityInventory {
  api_version: 2;
  enabled_plugins: string[];
  execution_host: 'codex_app';
}

export async function getCapabilityInventory(): Promise<CapabilityInventory> {
  const response = await apiFetch('/api/capabilities');
  if (!response.ok) throw new Error(`GET /api/capabilities failed: ${response.status}`);
  const body = await response.json();
  if (body.api_version !== 2 || body.execution_host !== 'codex_app' || !Array.isArray(body.enabled_plugins)
      || body.enabled_plugins.some((id: unknown) => typeof id !== 'string' || !id.trim() || id !== id.trim())
      || new Set(body.enabled_plugins).size !== body.enabled_plugins.length) {
    throw new Error('Unsupported capability inventory schema');
  }
  return body;
}
