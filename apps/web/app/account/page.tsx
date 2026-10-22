'use client';

// Account: personal API tokens for the Open API (integrations, BI, scripts).

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import { request, ApiError } from '@/lib/api';
import { getStoredUser } from '@/lib/auth';
import { absoluteUrl } from '@/lib/twin/api';
import { Button, ErrorBox, Field, Input } from '@/components/twin/ui';
import { locale, tr } from '@/lib/i18n';

interface Token {
  id: string;
  name: string;
  prefix: string;
  read_only: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

const d = (s: string | null) => (s ? new Date(s).toLocaleString(locale(), { dateStyle: 'short', timeStyle: 'short' }) : '—');

function AccountInner() {
  const user = getStoredUser();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [name, setName] = useState('');
  const [readOnly, setReadOnly] = useState(true);
  const [days, setDays] = useState('');
  const [created, setCreated] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => request<Token[]>('/api/tokens').then(setTokens).catch(() => {}), []);
  useEffect(() => {
    load();
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const t = await request<Token & { token: string }>('/api/tokens', {
        method: 'POST',
        body: JSON.stringify({ name, read_only: readOnly, expires_days: days ? Number(days) : null }),
      });
      setCreated(t.token);
      setName('');
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось создать'));
    }
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center gap-3 border-b border-bg-border px-4 py-3">
        <Link href="/projects" className="text-sm text-accent-teal hover:underline">{tr('← К проектам')}</Link>
        <h1 className="text-base font-semibold">{tr('Учётная запись')}</h1>
        <span className="ml-auto text-xs text-text-muted">{user?.full_name ?? user?.email}</span>
      </header>
      <main className="mx-auto max-w-3xl space-y-4 p-4">
        <section className="rounded-xl border border-bg-border bg-bg-panel p-4">
          <h2 className="text-sm font-semibold">{tr('API-токены')}</h2>
          <p className="mt-1 text-xs text-text-secondary">
            {tr('Для интеграций (1С, Power BI, скрипты): токен действует с вашими правами. Передавайте в заголовке')}{' '}
            <code className="text-text-primary">Authorization: Bearer twk_…</code>.{' '}
            {tr('Описание всех методов —')}{' '}
            <a href={absoluteUrl('/docs')} target="_blank" rel="noreferrer" className="text-accent-teal hover:underline">Swagger /docs</a>.
          </p>

          <form onSubmit={create} className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_120px_auto] sm:items-end">
            <Field label={tr('Название')}><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Power BI" required /></Field>
            <label className="flex items-center gap-1.5 pb-2 text-xs text-text-secondary">
              <input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} /> {tr('Только чтение')}
            </label>
            <Field label={tr('Срок, дней')}><Input value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" placeholder="∞" /></Field>
            <Button type="submit" variant="primary">{tr('Создать')}</Button>
          </form>
          {error && <div className="mt-2"><ErrorBox>{error}</ErrorBox></div>}
          {created && (
            <div className="mt-3 rounded-md border border-accent-teal/50 bg-accent-teal/10 p-3 text-xs">
              <div className="mb-1 font-semibold">{tr('Скопируйте токен сейчас — он больше не будет показан:')}</div>
              <code className="block break-all text-text-primary">{created}</code>
              <div className="mt-2 flex gap-2">
                <Button onClick={() => navigator.clipboard?.writeText(created)}>{tr('Копировать')}</Button>
                <Button variant="ghost" onClick={() => setCreated(null)}>{tr('Скрыть')}</Button>
              </div>
            </div>
          )}

          <table className="mt-4 w-full text-xs">
            <thead className="text-left text-text-secondary">
              <tr><th className="py-1">{tr('Название')}</th><th>{tr('Токен')}</th><th>{tr('Права')}</th><th>{tr('Использован')}</th><th>{tr('Истекает')}</th><th /></tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr key={t.id} className="border-t border-bg-border/60">
                  <td className="py-1.5">{t.name}</td>
                  <td><code className="text-text-muted">{t.prefix}…</code></td>
                  <td>{t.read_only ? tr('чтение') : tr('чтение и запись')}</td>
                  <td className="text-text-muted">{d(t.last_used_at)}</td>
                  <td className="text-text-muted">{d(t.expires_at)}</td>
                  <td className="text-right">
                    <button className="text-text-muted hover:text-red-300" onClick={async () => {
                      if (confirm(tr('Отозвать токен «{n}»?', { n: t.name }))) { await request(`/api/tokens/${t.id}`, { method: 'DELETE' }); load(); }
                    }}>{tr('Отозвать')}</button>
                  </td>
                </tr>
              ))}
              {tokens.length === 0 && <tr><td colSpan={6} className="py-2 text-text-muted">{tr('Токенов нет.')}</td></tr>}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}

export default function AccountPage() {
  return (
    <AuthGuard>
      <AccountInner />
    </AuthGuard>
  );
}
