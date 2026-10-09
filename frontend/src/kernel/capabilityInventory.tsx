import React from 'react';
import { getCapabilityInventory, type CapabilityInventory } from '../api/capabilities';

export type CapabilityState =
  | { status: 'loading'; inventory: null; error: null }
  | { status: 'ready'; inventory: CapabilityInventory; error: null }
  | { status: 'refreshing'; inventory: CapabilityInventory; error: null }
  | { status: 'stale'; inventory: CapabilityInventory; error: string }
  | { status: 'failed'; inventory: null; error: string };

export type CapabilityEvent =
  | { type: 'requested' }
  | { type: 'succeeded'; inventory: CapabilityInventory }
  | { type: 'failed'; error: string };

export type CapabilityInventoryResource = CapabilityState & { refresh(): Promise<void> };

export function reduceCapabilityState(state: CapabilityState, event: CapabilityEvent): CapabilityState {
  switch (event.type) {
    case 'requested':
      return state.inventory
        ? { status: 'refreshing', inventory: state.inventory, error: null }
        : { status: 'loading', inventory: null, error: null };
    case 'succeeded':
      return { status: 'ready', inventory: event.inventory, error: null };
    case 'failed':
      return state.inventory
        ? { status: 'stale', inventory: state.inventory, error: event.error }
        : { status: 'failed', inventory: null, error: event.error };
  }
}

const CapabilityInventoryContext = React.createContext<CapabilityInventoryResource | null>(null);

export const CapabilityInventoryProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, dispatch] = React.useReducer(
    reduceCapabilityState,
    { status: 'loading', inventory: null, error: null } as CapabilityState,
  );
  const mounted = React.useRef(false);
  const requestVersion = React.useRef(0);

  const refresh = React.useCallback(async () => {
    const version = ++requestVersion.current;
    dispatch({ type: 'requested' });
    try {
      const nextInventory = await getCapabilityInventory();
      if (!mounted.current || version !== requestVersion.current) return;
      dispatch({ type: 'succeeded', inventory: nextInventory });
    } catch (nextError) {
      if (!mounted.current || version !== requestVersion.current) return;
      dispatch({ type: 'failed', error: String(nextError) });
    }
  }, []);

  React.useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      requestVersion.current += 1;
    };
  }, [refresh]);

  const value = React.useMemo(
    () => ({ ...state, refresh }),
    [refresh, state],
  );
  return <CapabilityInventoryContext.Provider value={value}>{children}</CapabilityInventoryContext.Provider>;
};

export function useCapabilityInventory(): CapabilityInventoryResource {
  const context = React.useContext(CapabilityInventoryContext);
  if (!context) throw new Error('useCapabilityInventory must be used inside CapabilityInventoryProvider');
  return context;
}
