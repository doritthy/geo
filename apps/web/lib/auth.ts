'use client';

import { useEffect, useState } from 'react';
import type { User } from './types';

// Token storage: we use localStorage (not an httpOnly cookie).
//
// Tradeoff, documented per the task brief: an httpOnly cookie set by the
// backend would be more XSS-resistant, but this frontend and the FastAPI
// backend are on different origins/ports in dev (3000 vs 8000) and the
// contract's `/api/auth/login` simply returns a JSON `access_token` rather
// than setting a cookie itself -- so the natural client-side integration is
// to store the bearer token and attach it as an `Authorization` header on
// every request, which is what `lib/api.ts` does. localStorage is acceptable
// for this scope; a production hardening pass would move to an httpOnly
// cookie plus a small backend proxy/session endpoint.

const TOKEN_KEY = 'subsurface_token';
const USER_KEY = 'subsurface_user';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}

export function getStoredUser(): User | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: User): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* ignore */
  }
}

export function clearAuth(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

/**
 * Hook returning the current user from localStorage, refreshed from
 * `/api/auth/me` in the background. Returns `undefined` while loading,
 * `null` if unauthenticated, or the `User` once resolved.
 */
export function useCurrentUser(): { user: User | null | undefined; loading: boolean } {
  const [user, setUser] = useState<User | null | undefined>(() => getStoredUser() ?? undefined);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    import('./api').then(({ api }) => {
      api.me().then(
        (u) => {
          if (cancelled) return;
          setStoredUser(u);
          setUser(u);
          setLoading(false);
        },
        () => {
          if (cancelled) return;
          clearAuth();
          setUser(null);
          setLoading(false);
        }
      );
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { user, loading };
}
