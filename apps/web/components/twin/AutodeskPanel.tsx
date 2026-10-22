'use client';

import { useCallback, useEffect, useState } from 'react';
import { request, ApiError } from '@/lib/api';
import { Button, Empty, ErrorBox, Icons } from './ui';

interface ApsNode {
  id: string;
  type: 'hubs' | 'projects' | 'folders' | 'items';
  name: string;
  extension?: string | null;
  modified?: string | null;
}

interface LinkOut {
  id: string;
  name: string;
  item_id: string;
  status: 'pending' | 'translating' | 'ready' | 'error';
  error_message: string | null;
  watching: boolean;
  updated_at: string;
}

const STATUS: Record<LinkOut['status'], string> = {
  pending: 'в очереди',
  translating: 'конвертация RVT → IFC…',
  ready: 'актуально',
  error: 'ошибка',
};

const IMPORTABLE = /\.(ifc|rvt|nwd|nwc|dwg|las|laz|e57|obj|glb|gltf|ply|zip)$/i;

/** ACC / BIM 360: connect the Autodesk account, browse hubs → projects →
 * folders, import a model in one click (RVT is converted to IFC by APS
 * Model Derivative) and keep it updated via webhooks. */
export default function AutodeskPanel({ projectId, onImported }: { projectId: string; onImported: () => void }) {
  const [status, setStatus] = useState<{ configured: boolean; connected: boolean; webhooks: boolean } | null>(null);
  const [path, setPath] = useState<{ node: ApsNode; hubId?: string; projectId?: string }[]>([]);
  const [items, setItems] = useState<ApsNode[]>([]);
  const [links, setLinks] = useState<LinkOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [issueSync, setIssueSync] = useState<{ aps_project_id: string; last_pulled_at: string | null; last_result: Record<string, number | string> } | null>(null);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const loadLinks = useCallback(
    () => request<LinkOut[]>(`/api/projects/${projectId}/autodesk/imports`).then(setLinks).catch(() => {}),
    [projectId]
  );

  useEffect(() => {
    request<typeof status>('/api/integrations/autodesk/status').then(setStatus).catch(() => setStatus(null));
    loadLinks();
    request<typeof issueSync>(`/api/projects/${projectId}/autodesk/issues-sync`).then(setIssueSync).catch(() => {});
  }, [loadLinks, projectId]);

  async function configureIssueSync(apsProjectId: string) {
    setSyncMsg(null);
    try {
      setIssueSync(await request(`/api/projects/${projectId}/autodesk/issues-sync`, {
        method: 'POST', body: JSON.stringify({ aps_project_id: apsProjectId }),
      }));
      setSyncMsg('Проект ACC связан. Запустите синхронизацию.');
    } catch (err) {
      setSyncMsg(err instanceof ApiError ? err.detail : 'Не удалось настроить');
    }
  }

  async function runIssueSync() {
    setSyncMsg('Синхронизация…');
    try {
      const r = await request<Record<string, number>>(`/api/projects/${projectId}/autodesk/issues-sync/run`, { method: 'POST' });
      setSyncMsg(`Отправлено новых: ${r.pushed_new}, обновлено в ACC: ${r.pushed_updates}, получено изменений: ${r.pulled_updates}, импортировано из ACC: ${r.imported}`);
      request<typeof issueSync>(`/api/projects/${projectId}/autodesk/issues-sync`).then(setIssueSync).catch(() => {});
    } catch (err) {
      setSyncMsg(err instanceof ApiError ? err.detail : 'Ошибка синхронизации');
    }
  }

  // Poll while imports are running; refresh the scene when they finish.
  useEffect(() => {
    if (!links.some((l) => l.status === 'pending' || l.status === 'translating')) return;
    const t = setInterval(async () => {
      const next = await request<LinkOut[]>(`/api/projects/${projectId}/autodesk/imports`);
      setLinks(next);
      if (!next.some((l) => l.status === 'pending' || l.status === 'translating')) onImported();
    }, 4000);
    return () => clearInterval(t);
  }, [links, projectId, onImported]);

  const browse = useCallback(async (trail: typeof path) => {
    setLoading(true);
    setError(null);
    try {
      const last = trail[trail.length - 1];
      let url = '/api/integrations/autodesk/hubs';
      if (last?.node.type === 'hubs') url = `/api/integrations/autodesk/hubs/${encodeURIComponent(last.node.id)}/projects`;
      else if (last?.node.type === 'projects')
        url = `/api/integrations/autodesk/hubs/${encodeURIComponent(last.hubId!)}/projects/${encodeURIComponent(last.node.id)}/folders`;
      else if (last?.node.type === 'folders')
        url = `/api/integrations/autodesk/projects/${encodeURIComponent(last.projectId!)}/folders/${encodeURIComponent(last.node.id)}/contents`;
      setItems(await request<ApsNode[]>(url));
      setPath(trail);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Ошибка Autodesk API');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status?.connected) browse([]);
  }, [status?.connected, browse]);

  function open(node: ApsNode) {
    const last = path[path.length - 1];
    const hubId = node.type === 'hubs' ? node.id : last?.hubId;
    const apsProject = node.type === 'projects' ? node.id : last?.projectId;
    browse([...path, { node, hubId, projectId: apsProject }]);
  }

  async function importItem(node: ApsNode) {
    const last = path[path.length - 1];
    setError(null);
    try {
      await request(`/api/projects/${projectId}/autodesk/imports`, {
        method: 'POST',
        body: JSON.stringify({
          hub_id: last?.hubId,
          aps_project_id: last?.projectId,
          item_id: node.id,
          folder_id: last?.node.type === 'folders' ? last.node.id : null,
          name: node.name.replace(/\.[^.]+$/, ''),
          watch: true,
        }),
      });
      loadLinks();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Импорт не удался');
    }
  }

  async function connect() {
    const { url } = await request<{ url: string }>(
      `/api/integrations/autodesk/login?return_to=${encodeURIComponent(`/twin/${projectId}`)}`
    );
    window.location.href = url;
  }

  if (!status) return <Empty>Загрузка…</Empty>;
  if (!status.configured) {
    return (
      <Empty>
        Интеграция с Autodesk ACC / BIM 360 не настроена. Администратору: создайте приложение в APS
        (aps.autodesk.com) и задайте APS_CLIENT_ID, APS_CLIENT_SECRET и APS_CALLBACK_URL на сервере.
      </Empty>
    );
  }

  return (
    <div className="space-y-4">
      {!status.connected ? (
        <div className="space-y-2">
          <p className="text-xs text-text-secondary">Подключите аккаунт Autodesk, чтобы импортировать модели из ACC / BIM 360.</p>
          <Button variant="primary" onClick={connect}>Войти через Autodesk</Button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1 text-xs">
            <button className="text-accent-teal hover:underline" onClick={() => browse([])}>Хабы</button>
            {path.map((p, i) => (
              <span key={p.node.id} className="flex items-center gap-1">
                <span className="text-text-muted">/</span>
                <button className="max-w-[9rem] truncate text-accent-teal hover:underline" onClick={() => browse(path.slice(0, i + 1))}>
                  {p.node.name}
                </button>
              </span>
            ))}
          </div>
          {error && <ErrorBox>{error}</ErrorBox>}
          {loading ? (
            <div className="text-xs text-text-muted">Загрузка…</div>
          ) : items.length === 0 ? (
            <Empty>Пусто</Empty>
          ) : (
            <div className="space-y-1">
              {items.map((node) => (
                <div key={node.id} className="flex items-center gap-2 rounded-md border border-bg-border px-2 py-1.5 text-sm">
                  {node.type === 'items' ? (
                    <>
                      <span className="min-w-0 flex-1 truncate">{node.name}</span>
                      {IMPORTABLE.test(node.name) && (
                        <Button variant="primary" onClick={() => importItem(node)}>Импорт</Button>
                      )}
                    </>
                  ) : (
                    <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => open(node)}>
                      <span className="min-w-0 flex-1 truncate">{node.name}</span>
                      <span className="text-text-muted">{Icons.chevron}</span>
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {!status.webhooks && (
            <p className="text-[11px] text-text-muted">
              Автообновление по вебхукам выключено (не задан APS_WEBHOOK_URL) — используйте «Синхр.».
            </p>
          )}
        </div>
      )}

      {status.connected && (
        <div className="space-y-2 rounded-lg border border-bg-border p-3">
          <div className="text-sm font-semibold">Предписания ↔ ACC Issues</div>
          {issueSync ? (
            <>
              <div className="text-[11px] text-text-muted">
                Проект ACC {issueSync.aps_project_id.slice(0, 8)}… · последняя синхронизация{' '}
                {issueSync.last_pulled_at ? new Date(issueSync.last_pulled_at).toLocaleString('ru-RU') : '—'}
              </div>
              <Button variant="primary" onClick={runIssueSync}>Синхронизировать сейчас</Button>
            </>
          ) : path.find((p) => p.node.type === 'projects') ? (
            <Button onClick={() => configureIssueSync(path.find((p) => p.node.type === 'projects')!.node.id)}>
              Связать с проектом «{path.find((p) => p.node.type === 'projects')!.node.name}»
            </Button>
          ) : (
            <p className="text-[11px] text-text-muted">Откройте проект ACC в обзоре выше, чтобы связать с ним реестр предписаний.</p>
          )}
          {syncMsg && <div className="text-[11px] text-text-secondary">{syncMsg}</div>}
          <p className="text-[10px] text-text-muted">
            Статусы сопоставляются (На проверке ↔ in_review). Исполнители и «булавки» на чертежах не переносятся — ограничение API ACC.
          </p>
        </div>
      )}

      {links.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">Связанные модели</div>
          {links.map((l) => (
            <div key={l.id} className="rounded-md border border-bg-border px-2.5 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-text-primary">{l.name}</span>
                <Button
                  onClick={async () => {
                    await request(`/api/projects/${projectId}/autodesk/imports/${l.id}/sync`, { method: 'POST' });
                    loadLinks();
                  }}
                >
                  Синхр.
                </Button>
              </div>
              <div className={l.status === 'error' ? 'text-red-300' : 'text-text-muted'}>
                {STATUS[l.status]}
                {l.watching && ' · отслеживается'}
                {l.error_message && ` — ${l.error_message}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
