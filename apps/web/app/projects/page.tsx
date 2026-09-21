'use client';

import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import { api, ApiError } from '@/lib/api';
import { clearAuth, getStoredUser } from '@/lib/auth';
import type { Project } from '@/lib/types';

function CreateProjectDialog({ onCreated, onClose }: { onCreated: (p: Project) => void; onClose: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [crsEpsg, setCrsEpsg] = useState('32639');
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
        default_crs_epsg: crsEpsg ? Number(crsEpsg) : undefined,
      });
      onCreated(project);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to create project.');
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
        <h2 className="mb-4 text-lg font-semibold">New project</h2>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              Name
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder="North Field Development"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder="Optional"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-text-secondary">
              Default CRS (EPSG)
            </label>
            <input
              type="number"
              value={crsEpsg}
              onChange={(e) => setCrsEpsg(e.target.value)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent-teal"
              placeholder="32639"
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
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-accent-teal px-4 py-2 text-sm font-semibold text-bg hover:bg-accent-teal/90 disabled:opacity-50"
            >
              {loading ? 'Creating…' : 'Create project'}
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
  const user = getStoredUser();

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((err) => setError(err instanceof ApiError ? err.detail : 'Failed to load projects.'));
  }, []);

  function onLogout() {
    clearAuth();
    router.push('/login');
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center justify-between border-b border-bg-border px-6 py-4">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-md bg-gradient-to-br from-accent-teal to-accent-blue" />
          <span className="text-base font-semibold tracking-tight">Subsurface 3D Workspace</span>
        </div>
        <div className="flex items-center gap-4 text-sm text-text-secondary">
          {user && <span>{user.full_name ?? user.email}</span>}
          <button onClick={onLogout} className="rounded-md border border-bg-border px-3 py-1.5 hover:text-text-primary">
            Sign out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Projects</h1>
            <p className="text-sm text-text-secondary">Select a project workspace, or create a new one.</p>
          </div>
          <button
            onClick={() => setDialogOpen(true)}
            className="rounded-md bg-accent-teal px-4 py-2 text-sm font-semibold text-bg hover:bg-accent-teal/90"
          >
            + New project
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {!projects && !error && <div className="text-sm text-text-secondary">Loading projects…</div>}

        {projects && projects.length === 0 && (
          <div className="rounded-xl border border-dashed border-bg-border p-10 text-center text-text-secondary">
            No projects yet. Create your first project to start uploading data.
          </div>
        )}

        {projects && projects.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="group rounded-xl border border-bg-border bg-bg-panel p-5 transition hover:border-accent-teal/60 hover:bg-bg-panel2"
              >
                <h3 className="mb-1 font-semibold text-text-primary group-hover:text-accent-teal">{p.name}</h3>
                <p className="mb-3 line-clamp-2 text-sm text-text-secondary">{p.description || 'No description'}</p>
                <div className="flex items-center justify-between text-xs text-text-muted">
                  <span>EPSG:{p.default_crs_epsg}</span>
                  <span>{new Date(p.created_at).toLocaleDateString()}</span>
                </div>
              </Link>
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
            router.push(`/projects/${p.id}`);
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
