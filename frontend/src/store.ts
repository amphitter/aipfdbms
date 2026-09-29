import { create } from "zustand";
import { clearToken, getToken, setToken, type User } from "./api";

type Toast = { id: number; text: string; tone?: "ok" | "bad" | "warn" };

type State = {
  user: User | null;
  token: string;
  tick: number;
  toasts: Toast[];
  setSession: (token: string, user: User) => void;
  setUser: (user: User | null) => void;
  clear: () => void;
  bump: () => void;
  toast: (text: string, tone?: "ok" | "bad" | "warn") => void;
  dismiss: (id: number) => void;
  can: (permission: string) => boolean;
};

export const useApp = create<State>((set, get) => ({
  user: null,
  token: getToken(),
  tick: 0,
  toasts: [],
  setSession: (token, user) => {
    setToken(token);
    set({ token, user });
  },
  setUser: (user) => set({ user }),
  clear: () => {
    clearToken();
    set({ token: "", user: null });
  },
  bump: () => set((s) => ({ tick: s.tick + 1 })),
  toast: (text, tone) => {
    const id = Date.now() + Math.random();
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }));
    window.setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 4600);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  can: (permission) => {
    const user = get().user;
    if (!user) return false;
    return user.permissions.includes(permission);
  },
}));
