'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login({ email, password });
      router.push('/projects');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-bg-border bg-bg-panel p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-2">
          <div className="h-8 w-8 rounded-md bg-gradient-to-br from-accent-teal to-accent-blue" />
          <span className="text-lg font-semibold tracking-tight">Subsurface 3D</span>
        </div>
        <h1 className="mb-1 text-xl font-semibold text-text-primary">Sign in</h1>
        <p className="mb-6 text-sm text-text-secondary">Access your organization&apos;s workspace.</p>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-teal"
              placeholder="you@company.com"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-teal"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-accent-teal px-3 py-2 text-sm font-semibold text-bg transition hover:bg-accent-teal/90 disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-text-secondary">
          No account?{' '}
          <Link href="/register" className="text-accent-teal hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
