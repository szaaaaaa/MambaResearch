import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { CredentialStatusMap, Credentials } from './types';

export const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

const defaultCredentials: Credentials = {
  OPENAI_API_KEY: '',
  GEMINI_API_KEY: '',
  OPENROUTER_API_KEY: '',
  SILICONFLOW_API_KEY: '',
  GOOGLE_API_KEY: '',
  SERPAPI_API_KEY: '',
  GOOGLE_CSE_API_KEY: '',
  GOOGLE_CSE_CX: '',
  BING_API_KEY: '',
  GITHUB_TOKEN: '',
  ZOTERO_USER_ID: '',
  ZOTERO_API_KEY: '',
};

const defaultCredentialStatus: CredentialStatusMap = {
  OPENAI_API_KEY: { present: false, source: 'missing' },
  GEMINI_API_KEY: { present: false, source: 'missing' },
  OPENROUTER_API_KEY: { present: false, source: 'missing' },
  SILICONFLOW_API_KEY: { present: false, source: 'missing' },
  GOOGLE_API_KEY: { present: false, source: 'missing' },
  SERPAPI_API_KEY: { present: false, source: 'missing' },
  GOOGLE_CSE_API_KEY: { present: false, source: 'missing' },
  GOOGLE_CSE_CX: { present: false, source: 'missing' },
  BING_API_KEY: { present: false, source: 'missing' },
  GITHUB_TOKEN: { present: false, source: 'missing' },
  ZOTERO_USER_ID: { present: false, source: 'missing' },
  ZOTERO_API_KEY: { present: false, source: 'missing' },
};

interface AppState {
  credentials: Credentials;
  credentialStatus: CredentialStatusMap;
}

interface AppContextType {
  state: AppState;
  updateCredentials: (updates: Partial<Credentials>) => void;
  saveCredentials: () => Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    // The status below is the useful fallback.
  }
  return `HTTP ${response.status}`;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const credentialsRef = useRef<Credentials>(defaultCredentials);
  const [state, setState] = useState<AppState>({
    credentials: defaultCredentials,
    credentialStatus: defaultCredentialStatus,
  });

  useEffect(() => {
    fetch(`${API_BASE}/api/credentials`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await readErrorDetail(response));
        return response.json();
      })
      .then((payload) => {
        if (!isRecord(payload)) return;
        const values = isRecord(payload.values) ? payload.values : {};
        const status = isRecord(payload.status) ? payload.status : {};
        const credentials = { ...defaultCredentials, ...(values as Partial<Credentials>) };
        credentialsRef.current = credentials;
        setState({
          credentials,
          credentialStatus: { ...defaultCredentialStatus, ...(status as Partial<CredentialStatusMap>) },
        });
      })
      .catch((error) => console.error('Failed to load credentials', error));
  }, []);

  const updateCredentials = (updates: Partial<Credentials>) => {
    const credentials = { ...credentialsRef.current, ...updates };
    credentialsRef.current = credentials;
    setState((current) => ({ ...current, credentials }));
  };

  const saveCredentials = async () => {
    const response = await fetch(`${API_BASE}/api/credentials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentialsRef.current),
    });
    if (!response.ok) throw new Error(await readErrorDetail(response));
    const payload = await response.json();
    const status = isRecord(payload) && isRecord(payload.status) ? payload.status : {};
    setState((current) => ({
      ...current,
      credentialStatus: { ...defaultCredentialStatus, ...(status as Partial<CredentialStatusMap>) },
    }));
  };

  return (
    <AppContext.Provider value={{ state, updateCredentials, saveCredentials }}>
      {children}
    </AppContext.Provider>
  );
};

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppContext must be used within AppProvider');
  return context;
};
