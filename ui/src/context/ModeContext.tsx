'use client';

import { createContext, useContext, useEffect, useState } from 'react';

export type WorkspaceMode = 'organization' | 'creative';

interface ModeContextType {
  mode: WorkspaceMode;
  setMode: (mode: WorkspaceMode) => void;
  /**
   * False until the stored mode has been read from localStorage. Creative pages
   * must gate on this: before hydration every visitor still reads as
   * 'organization', and a gate that acted on that would bounce a creative-mode
   * user off the page on every hard reload.
   */
  hydrated: boolean;
}

const ModeContext = createContext<ModeContextType | null>(null);

const MODE_STORAGE_KEY = 'dograh-mode';

function readStoredMode(): WorkspaceMode | null {
  try {
    const stored = localStorage.getItem(MODE_STORAGE_KEY);
    return stored === 'creative' || stored === 'organization' ? stored : null;
  } catch {
    return null;
  }
}

export function ModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<WorkspaceMode>('organization');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = readStoredMode();
    if (stored) {
      setModeState(stored);
    }
    setHydrated(true);
  }, []);

  const setMode = (next: WorkspaceMode) => {
    setModeState(next);
    try {
      localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      // Private-browsing storage failures must not break the toggle; the mode
      // simply resets to organization on the next full page load.
    }
  };

  return (
    <ModeContext.Provider value={{ mode, setMode, hydrated }}>
      {children}
    </ModeContext.Provider>
  );
}

export function useMode() {
  const context = useContext(ModeContext);
  if (!context) {
    throw new Error('useMode must be used within ModeProvider');
  }
  return context;
}
