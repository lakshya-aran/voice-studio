import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, post, tokenStore, type User } from "./api";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false));
    const onLogout = () => setUser(null);
    window.addEventListener("vs:logout", onLogout);
    return () => window.removeEventListener("vs:logout", onLogout);
  }, []);

  const finish = (r: { access_token: string; user: User }) => {
    tokenStore.set(r.access_token);
    setUser(r.user);
  };

  const login = useCallback(async (email: string, password: string) => {
    finish(await post("/auth/login", { email, password }));
  }, []);
  const register = useCallback(async (name: string, email: string, password: string) => {
    finish(await post("/auth/register", { name, email, password }));
  }, []);
  const logout = useCallback(() => {
    tokenStore.set(null);
    setUser(null);
  }, []);

  return <Ctx.Provider value={{ user, loading, login, register, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside provider");
  return v;
}
