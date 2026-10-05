import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import * as api from '../services/api';
import { CurrentUser } from '../types';

interface AuthContextValue {
  /** undefined while the first check is in flight; null when signed out. */
  user: CurrentUser | null | undefined;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: undefined,
  refresh: async () => undefined,
  signOut: async () => undefined,
});

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.getMe());
    } catch {
      // 401 (not signed in) and 403 (removed from the invite list) both
      // land on the sign-in page.
      setUser(null);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    // A session can expire while the app is open; any 401 signs the user out
    // locally rather than leaving every panel showing its own error.
    api.setUnauthorizedHandler(() => setUser(null));
    return () => api.setUnauthorizedHandler(null);
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, refresh, signOut }}>{children}</AuthContext.Provider>
  );
};
