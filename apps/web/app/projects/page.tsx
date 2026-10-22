'use client';

import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import { api, ApiError } from '@/lib/api';
import { clearAuth, useStoredUser } from '@/lib/auth';
import type { Project } from '@/lib/types';
import { tr, locale } from '@/lib/i18n';
import LangSwitch from '@/components/LangSwitch';
import { BrandMark } from '@/components/Branding';

function CreateProjectDialog({ onCreated, onClose }: { onCreated: (p: Project) => void; onClose: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [crs, setCrs] = useState('EPSG:32642');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const project = await api.createProject({
        name,
        description: description || undefined,
        crs: crs || undefined,
        default_crs_epsg: /^(EPSG:)?\d+$/i.test(crs) ? Number(crs.replace(/^EPSG:/i, '')) : undefined,
      });
      onCreated(project);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось создать проект.'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-xl border border-bg-border bg-bg-panel p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold">{tr('Новый проект')}</h2>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              {tr('Название')}
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder={tr('ЖК «Северный», очередь 1')}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              {tr('Описание')}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder={tr('Необязательно')}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              {tr('Система координат (EPSG / PROJ)')}
            </label>
            <input
              value={crs}
              onChange={(e) => setCrs(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder="EPSG:32642"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-bg-border px-3 py-2 text-sm text-text-secondary hover:text-text-primary"
            >
              {tr('Отмена')}
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-accent-teal px-4 py-2 text-sm font-semibold text-bg hover:bg-accent-teal/90 disabled:opacity-50"
            >
              {loading ? tr('Создание…') : tr('Создать проект')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ProjectsPageInner() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const user = useStoredUser();

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((err) => setError(err instanceof ApiError ? err.detail : tr('Не удалось загрузить проекты.')));
  }, []);

  function onLogout() {
    clearAuth();
    router.push('/login');
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center justify-between border-b border-bg-border px-6 py-4">
        <div className="flex items-center gap-2">
          <BrandMark fallback={tr('Цифровой двойник строительства')} nameClassName="text-base font-semibold tracking-tight" />
        </div>
        <div className="flex items-center gap-4 text-sm text-text-secondary">
          <Link href="/portfolio" className="rounded-md border border-bg-border px-3 py-1.5 hover:text-text-primary">{tr('Портфель')}</Link>
          <LangSwitch />
          {user && <Link href="/account" className="hover:text-text-primary" title={tr('Учётная запись и API-токены')}>{user.full_name ?? user.email}</Link>}
          <button onClick={onLogout} className="rounded-md border border-bg-border px-3 py-1.5 hover:text-text-primary">
            {tr('Выйти')}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">{tr('Проекты')}</h1>
            <p className="text-sm text-text-secondary">{tr('Выберите объект строительства или создайте новый.')}</p>
          </div>
          <button
            onClick={() => setDialogOpen(true)}
            className="rounded-md bg-accent-teal px-4 py-2 text-sm font-semibold text-bg hover:bg-accent-teal/90"
          >
            {tr('+ Новый проект')}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {!projects && !error && <div className="text-sm text-text-secondary">{tr('Загрузка проектов…')}</div>}

        {projects && projects.length === 0 && (
          <div className="rounded-xl border border-dashed border-bg-border p-10 text-center text-text-secondary">
            {tr('Проектов пока нет. Создайте первый проект, чтобы загрузить модели и съёмку.')}
          </div>
        )}

        {projects && projects.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div
                key={p.id}
                className="group relative rounded-xl border border-bg-border bg-bg-panel p-5 transition hover:border-accent-teal/60 hover:bg-bg-panel2"
              >
                <Link href={`/twin/${p.id}`} className="absolute inset-0" aria-label={p.name} />
                <h3 className="mb-1 font-semibold text-text-primary group-hover:text-accent-teal">{p.name}</h3>
                <p className="mb-3 line-clamp-2 text-sm text-text-secondary">{p.description || tr('Без описания')}</p>
                <div className="flex items-center justify-between text-xs text-text-muted">
                  <span>{p.crs ?? `EPSG:${p.default_crs_epsg}`}</span>
                  <span className="flex items-center gap-3">
                    <Link href={`/projects/${p.id}`} className="relative z-10 hover:text-text-primary">{tr('Геология')}</Link>
                    <span>{new Date(p.created_at).toLocaleDateString(locale())}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {dialogOpen && (
        <CreateProjectDialog
          onClose={() => setDialogOpen(false)}
          onCreated={(p) => {
            setProjects((prev) => [p, ...(prev ?? [])]);
            setDialogOpen(false);
            router.push(`/twin/${p.id}`);
          }}
        />
      )}
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <AuthGuard>
      <ProjectsPageInner />
    </AuthGuard>
  );
}
