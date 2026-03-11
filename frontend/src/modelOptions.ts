import { AgentRoleId, ProviderModelCatalog, SelectOption } from './types';

type CatalogBundle = {
  openaiCatalog?: ProviderModelCatalog;
  geminiCatalog?: ProviderModelCatalog;
  openrouterCatalog?: ProviderModelCatalog;
  siliconflowCatalog?: ProviderModelCatalog;
};

export const LLM_PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'siliconflow', label: 'SiliconFlow' },
];

const VENDOR_LABELS: Record<string, string> = {
  allenai: 'AllenAI',
  anthropic: 'Anthropic',
  baai: 'BAAI',
  bytedance: 'ByteDance',
  cohere: 'Cohere',
  deepseek: 'DeepSeek',
  'deepseek-ai': 'DeepSeek',
  google: 'Google',
  internlm: 'InternLM',
  minimax: 'MiniMax',
  'meta-llama': 'Meta Llama',
  microsoft: 'Microsoft',
  mistralai: 'Mistral',
  moonshotai: 'Moonshot AI',
  nvidia: 'NVIDIA',
  openai: 'OpenAI',
  openbmb: 'OpenBMB',
  other: '其他',
  perplexity: 'Perplexity',
  qwen: 'Qwen',
  stabilityai: 'Stability AI',
  thudm: 'THUDM',
  'x-ai': 'xAI',
  zhipuai: 'Zhipu AI',
};

function titleCaseVendor(vendor: string): string {
  return vendor.replace(/[-_]/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function resolveCatalogBundle(maybeCatalogOrBundle?: CatalogBundle): CatalogBundle {
  if (!maybeCatalogOrBundle) {
    return {};
  }
  return maybeCatalogOrBundle;
}

function getVendorLabel(vendor: string): string {
  return VENDOR_LABELS[vendor] ?? titleCaseVendor(vendor);
}

function getDynamicModelsByVendor(catalog?: ProviderModelCatalog): Record<string, SelectOption[]> {
  if (!catalog || !catalog.loaded) {
    return {};
  }
  return catalog.modelsByVendor;
}

function getModelsByVendorForProvider(provider: string, bundle: CatalogBundle): Record<string, SelectOption[]> {
  if (provider === 'openai') {
    return getDynamicModelsByVendor(bundle.openaiCatalog);
  }
  if (provider === 'gemini') {
    return getDynamicModelsByVendor(bundle.geminiCatalog);
  }
  if (provider === 'openrouter') {
    return getDynamicModelsByVendor(bundle.openrouterCatalog);
  }
  if (provider === 'siliconflow') {
    return getDynamicModelsByVendor(bundle.siliconflowCatalog);
  }
  return {};
}

function inferVendorFromModelId(model: string): string {
  const trimmed = String(model || '').trim().toLowerCase();
  return trimmed.split('/', 1)[0] || '';
}

export function isVendorScopedProvider(provider: string): boolean {
  return provider === 'openrouter' || provider === 'siliconflow';
}

export function getVendorOptionsForProvider(
  provider: string,
  maybeCatalogOrBundle?: CatalogBundle,
): SelectOption[] {
  const bundle = resolveCatalogBundle(maybeCatalogOrBundle);
  return Object.keys(getModelsByVendorForProvider(provider, bundle))
    .sort((left, right) => getVendorLabel(left).localeCompare(getVendorLabel(right)))
    .map((vendor) => ({ value: vendor, label: getVendorLabel(vendor) }));
}

export function getModelsForProviderVendor(
  provider: string,
  vendor: string,
  maybeCatalogOrBundle?: CatalogBundle,
): SelectOption[] {
  const bundle = resolveCatalogBundle(maybeCatalogOrBundle);
  return getModelsByVendorForProvider(provider, bundle)[vendor] ?? [];
}

export function getVendorFromProviderModel(
  provider: string,
  model: string,
  maybeCatalogOrBundle?: CatalogBundle,
): string {
  const bundle = resolveCatalogBundle(maybeCatalogOrBundle);
  const inferredVendor = inferVendorFromModelId(model);
  if (inferredVendor && getModelsByVendorForProvider(provider, bundle)[inferredVendor]) {
    return inferredVendor;
  }
  return getVendorOptionsForProvider(provider, bundle)[0]?.value ?? inferredVendor ?? '';
}

export function getModelOptionsForProvider(
  provider: string,
  maybeCatalogOrBundle?: CatalogBundle,
): SelectOption[] {
  const bundle = resolveCatalogBundle(maybeCatalogOrBundle);
  return getVendorOptionsForProvider(provider, bundle).flatMap((vendor) =>
    getModelsForProviderVendor(provider, vendor.value, bundle),
  );
}

export function getFirstModelForProvider(
  provider: string,
  maybeCatalogOrBundle?: CatalogBundle,
): string {
  return getModelOptionsForProvider(provider, maybeCatalogOrBundle)[0]?.value ?? '';
}

export const AGENT_ROLE_LABELS: Record<AgentRoleId, string> = {
  conductor: '统筹agent',
  researcher: '研究agent',
  experimenter: '实验agent',
  analyst: '分析agent',
  writer: '写作agent',
  critic: '评审agent',
};
