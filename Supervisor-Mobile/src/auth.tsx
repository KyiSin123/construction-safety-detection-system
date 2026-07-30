import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, Supervisor } from './api';
import { tokenStorage } from './token-storage';

type AuthContextValue = { token: string | null; supervisor: Supervisor | null; loading: boolean; signIn: (username: string, password: string) => Promise<void>; signOut: () => Promise<void> };
const AuthContext = createContext<AuthContextValue | null>(null);
const TOKEN_KEY = 'ppe_supervisor_token';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null); const [supervisor, setSupervisor] = useState<Supervisor | null>(null); const [loading, setLoading] = useState(true);
  useEffect(() => { (async () => { const stored = await tokenStorage.getItemAsync(TOKEN_KEY); if (stored) { try { setSupervisor(await api.me(stored)); setToken(stored); } catch { await tokenStorage.deleteItemAsync(TOKEN_KEY); } } setLoading(false); })(); }, []);
  const value = useMemo(() => ({ token, supervisor, loading, signIn: async (username: string, password: string) => { const result = await api.login(username, password); await tokenStorage.setItemAsync(TOKEN_KEY, result.access_token); setToken(result.access_token); setSupervisor(result.supervisor); }, signOut: async () => { if (token) { try { await api.unregisterDevice(token); } catch {} } await tokenStorage.deleteItemAsync(TOKEN_KEY); setToken(null); setSupervisor(null); } }), [token, supervisor, loading]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error('AuthProvider is required'); return value; }
