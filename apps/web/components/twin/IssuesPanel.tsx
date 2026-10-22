'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import {
  ISSUE_NEXT,
  ISSUE_STATUS,
  PRIORITY_LABELS,
  type IssueDetail,
  type IssueKind,
  type IssuePriority,
  type Member,
} from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Icons, Input, Select } from './ui';
import { tr, locale } from '@/lib/i18n';

function StatusBadge({ status }: { status: keyof typeof ISSUE_STATUS }) {
  const s = ISSUE_STATUS[status];
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: `${s.color}22`, color: s.color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

function Photo({ id, name }: { id: string; name: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    twinApi.attachmentUrl(id).then((x) => setUrl((u = x))).catch(() => {});
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [id]);
  if (!url) return <div className="h-20 w-20 animate-pulse rounded bg-bg-panel2" />;
  return (
    <a href={url} target="_blank" rel="noreferrer" title={name}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={name} className="h-20 w-20 rounded object-cover" />
    </a>
  );
}

const EVENT_LABELS: Record<string, string> = {
  created: tr('создал(а)'),
  status: tr('изменил(а) статус'),
  assigned: tr('назначил(а) исполнителя'),
  updated: tr('изменил(а) поля'),
  comment: '',
  attachment: tr('добавил(а) файл'),
};

function IssueCard({ id, members, onChanged, onClose }: { id: string; members: Member[]; onChanged: () => void; onClose: () => void }) {
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [issue, setIssue] = useState<IssueDetail | null>(null);
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    twinApi.getIssue(id).then(setIssue).catch(() => setError(tr('Предписание не найдено')));
  }, [id]);

  async function act(fn: () => Promise<IssueDetail>) {
    setBusy(true);
    setError(null);
    try {
      setIssue(await fn());
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Ошибка'));
    } finally {
      setBusy(false);
    }
  }

  if (error && !issue) return <ErrorBox>{error}</ErrorBox>;
  if (!issue) return <div className="text-xs text-text-muted">{tr('Загрузка…')}</div>;
  const images = issue.attachments.filter((a) => (a.content_type ?? '').startsWith('image/'));
  const files = issue.attachments.filter((a) => !(a.content_type ?? '').startsWith('image/'));

  return (
    <div className="space-y-3">
      <button onClick={onClose} className="text-xs text-accent-teal hover:underline">{tr('← К реестру')}</button>
      <div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">{issue.kind === 'prescription' ? tr('Предписание') : tr('Замечание')} №{issue.number}</span>
          <StatusBadge status={issue.status} />
          {issue.overdue && <span className="text-[10px] font-semibold text-red-400">{tr('просрочено')}</span>}
        </div>
        <div className="mt-1 text-base font-semibold">{issue.title}</div>
        {issue.description && <p className="mt-1 whitespace-pre-wrap text-sm text-text-secondary">{issue.description}</p>}
      </div>

      <div className="flex flex-wrap gap-2">
        {ISSUE_NEXT[issue.status].map((n) => (
          <Button key={n.to} variant={n.to === 'closed' || n.to === 'review' || n.to === 'in_progress' ? 'primary' : 'secondary'} disabled={busy}
            onClick={() => act(() => twinApi.updateIssue(issue.id, { status: n.to }))}>
            {n.label}
          </Button>
        ))}
        {issue.longitude !== null && (
          <Button variant="ghost" onClick={() => requestFlyTo({ issueId: issue.id })}>{Icons.target}</Button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label={tr('Исполнитель')}>
          <Select value={issue.assignee_id ?? ''} onChange={(e) => act(() => twinApi.updateIssue(issue.id, { assignee_id: e.target.value || null }))}>
            <option value="">{tr('— не назначен —')}</option>
            {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </Select>
        </Field>
        <Field label={tr('Срок')}>
          <Input type="date" value={issue.due_date ?? ''} onChange={(e) => act(() => twinApi.updateIssue(issue.id, { due_date: e.target.value || null }))} />
        </Field>
        <Field label={tr('Приоритет')}>
          <Select value={issue.priority} onChange={(e) => act(() => twinApi.updateIssue(issue.id, { priority: e.target.value }))}>
            {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        <Field label={tr('Тип')}>
          <Select value={issue.kind} onChange={(e) => act(() => twinApi.updateIssue(issue.id, { kind: e.target.value }))}>
            <option value="remark">{tr('Замечание')}</option>
            <option value="prescription">{tr('Предписание')}</option>
          </Select>
        </Field>
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wide text-text-secondary">{tr('Фото и файлы')}</span>
          <label className="cursor-pointer rounded-md border border-bg-border px-2 py-1 text-xs text-text-secondary hover:text-text-primary">
            {tr('+ Фото')}
            <input type="file" accept="image/*" capture="environment" className="hidden"
              onChange={(e) => e.target.files?.[0] && act(() => twinApi.attachToIssue(issue.id, e.target.files![0]))} />
          </label>
        </div>
        {images.length > 0 && <div className="flex flex-wrap gap-2">{images.map((a) => <Photo key={a.id} id={a.id} name={a.filename} />)}</div>}
        {files.map((a) => (
          <button key={a.id} className="block text-xs text-accent-teal hover:underline"
            onClick={async () => window.open(await twinApi.attachmentUrl(a.id), '_blank')}>
            {a.filename}
          </button>
        ))}
        {issue.attachments.length === 0 && <div className="text-xs text-text-muted">{tr('Нет вложений')}</div>}
      </div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-text-secondary">{tr('История')}</div>
        <div className="space-y-1.5">
          {issue.events.map((e) => (
            <div key={e.id} className="text-xs">
              <span className="text-text-muted">{new Date(e.created_at).toLocaleString(locale())} · </span>
              <span className="text-text-secondary">{e.user_name ?? '—'} </span>
              {e.kind === 'comment' ? (
                <div className="mt-0.5 whitespace-pre-wrap rounded bg-bg-panel2 px-2 py-1 text-text-primary">{String(e.data.text)}</div>
              ) : (
                <span className="text-text-secondary">
                  {EVENT_LABELS[e.kind] ?? e.kind}
                  {e.kind === 'status' && ` → ${ISSUE_STATUS[e.data.to as keyof typeof ISSUE_STATUS]?.label ?? e.data.to}`}
                  {e.kind === 'attachment' && ` «${e.data.filename}»`}
                </span>
              )}
            </div>
          ))}
        </div>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (comment.trim()) act(() => twinApi.commentIssue(issue.id, comment.trim())).then(() => setComment(''));
          }}
        >
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder={tr('Комментарий…')} />
          <Button type="submit" disabled={!comment.trim() || busy}>OK</Button>
        </form>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
    </div>
  );
}

function NewIssueForm({ projectId, members, onDone }: { projectId: string; members: Member[]; onDone: (id?: string) => void }) {
  const point = useTwinStore((s) => s.pendingIssuePoint);
  const setPoint = useTwinStore((s) => s.setPendingIssuePoint);
  const setTool = useTwinStore((s) => s.setTool);
  const tool = useTwinStore((s) => s.tool);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [kind, setKind] = useState<IssueKind>('prescription');
  const [priority, setPriority] = useState<IssuePriority>('normal');
  const [assignee, setAssignee] = useState('');
  const [due, setDue] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [geo, setGeo] = useState<{ longitude: number; latitude: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function useMyLocation() {
    navigator.geolocation?.getCurrentPosition(
      (p) => setGeo({ longitude: p.coords.longitude, latitude: p.coords.latitude }),
      () => setError(tr('Не удалось получить геопозицию')),
      { enableHighAccuracy: true, timeout: 15000 }
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const loc = point ?? (geo ? { ...geo, height: null } : null);
      const issue = await twinApi.createIssue(projectId, {
        title, description: description || null, kind, priority, assignee_id: assignee || null, due_date: due || null,
        longitude: loc?.longitude ?? null, latitude: loc?.latitude ?? null, height: loc?.height ?? null,
        asset_id: point?.assetId ?? null, element_global_id: point?.globalId ?? null,
      });
      if (photo) await twinApi.attachToIssue(issue.id, photo);
      setPoint(null);
      onDone(issue.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось создать'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-lg border border-accent-teal/40 bg-bg-panel2/50 p-3">
      <div className="flex gap-2">
        <Select value={kind} onChange={(e) => setKind(e.target.value as IssueKind)}>
          <option value="prescription">{tr('Предписание')}</option>
          <option value="remark">{tr('Замечание')}</option>
        </Select>
        <Select value={priority} onChange={(e) => setPriority(e.target.value as IssuePriority)}>
          {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr('Суть нарушения')} required autoFocus />
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder={tr('Описание, требование, ссылка на норматив')}
        className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-1.5 text-sm outline-none focus:border-accent-teal" />
      <div className="grid grid-cols-2 gap-2">
        <Select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
          <option value="">{tr('Исполнитель…')}</option>
          {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </Select>
        <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} title={tr('Срок устранения')} />
      </div>
      <div className="space-y-1 text-xs text-text-secondary">
        <div>
          Место:{' '}
          {point ? (
            <span className="text-accent-teal">{tr('точка на модели')}{point.globalId ? tr(' · элемент') : ''}</span>
          ) : geo ? (
            <span className="text-accent-teal">{tr('геопозиция')} {geo.latitude.toFixed(5)}, {geo.longitude.toFixed(5)}</span>
          ) : (
            <span>{tr('не указано (возьмём из GPS фото, если есть)')}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant={tool === 'issue' ? 'primary' : 'secondary'} onClick={() => setTool(tool === 'issue' ? 'select' : 'issue')}>
            {tool === 'issue' ? tr('Кликните по модели…') : tr('Указать на модели')}
          </Button>
          <Button type="button" onClick={useMyLocation}>{tr('Моя геопозиция')}</Button>
          <label className="cursor-pointer rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary">
            {photo ? `${tr('Фото')}: ${photo.name}` : tr('Сделать фото')}
            <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          </label>
        </div>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={saving || !title.trim()}>{saving ? tr('Создание…') : tr('Создать')}</Button>
        <Button type="button" onClick={() => { setPoint(null); onDone(); }}>{tr('Отмена')}</Button>
      </div>
    </form>
  );
}

export default function IssuesPanel({ projectId }: { projectId: string }) {
  const issues = useTwinStore((s) => s.issues);
  const setIssues = useTwinStore((s) => s.setIssues);
  const openId = useTwinStore((s) => s.openIssueId);
  const setOpenId = useTwinStore((s) => s.setOpenIssueId);
  const pendingPoint = useTwinStore((s) => s.pendingIssuePoint);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [members, setMembers] = useState<Member[]>([]);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState('open,in_progress,review');
  const [assignee, setAssignee] = useState('');
  const [overdue, setOverdue] = useState(false);
  const [q, setQ] = useState('');

  const filters = { status: status || undefined, assignee: assignee || undefined, overdue: overdue ? 'true' : undefined, q: q || undefined };
  const load = useCallback(
    () => twinApi.listIssues(projectId, { status: status || undefined, assignee: assignee || undefined, overdue, q: q || undefined }).then(setIssues),
    [projectId, status, assignee, overdue, q, setIssues]
  );

  useEffect(() => {
    twinApi.members(projectId).then(setMembers).catch(() => {});
  }, [projectId]);
  useEffect(() => {
    const t = setTimeout(() => load().catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => {
    if (pendingPoint) setCreating(true);
  }, [pendingPoint]);

  if (openId) return <IssueCard id={openId} members={members} onChanged={load} onClose={() => setOpenId(null)} />;

  const counts = issues.reduce<Record<string, number>>((acc, i) => ({ ...acc, [i.status]: (acc[i.status] ?? 0) + 1 }), {});

  return (
    <div className="space-y-3">
      {creating ? (
        <NewIssueForm projectId={projectId} members={members} onDone={(id) => { setCreating(false); load(); if (id) setOpenId(id); }} />
      ) : (
        <Button variant="primary" onClick={() => setCreating(true)}>{tr('+ Новое предписание')}</Button>
      )}
      <div className="flex flex-wrap gap-2">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="flex-1">
          <option value="open,in_progress,review">{tr('Активные')}</option>
          <option value="open">{tr('Открытые')}</option>
          <option value="in_progress">{tr('В работе')}</option>
          <option value="review">{tr('На проверке')}</option>
          <option value="closed">{tr('Закрытые')}</option>
          <option value="">{tr('Все')}</option>
        </Select>
        <Select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="flex-1">
          <option value="">{tr('Все исполнители')}</option>
          <option value="me">{tr('Мои')}</option>
          {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </Select>
      </div>
      <div className="flex items-center gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr('Поиск или №')} />
        <label className="flex shrink-0 items-center gap-1 text-xs text-text-secondary">
          <input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /> {tr('Просрочены')}
        </label>
      </div>
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        <span>
          {issues.length} {tr('шт.')}{Object.entries(counts).map(([k, v]) => ` · ${ISSUE_STATUS[k as keyof typeof ISSUE_STATUS].label.toLowerCase()} ${v}`)}
        </span>
        <span className="flex gap-2">
          <button className="hover:text-text-primary" onClick={() => twinApi.downloadIssues(projectId, 'xlsx', filters)}>Excel</button>
          <button className="hover:text-text-primary" onClick={() => twinApi.downloadIssues(projectId, 'pdf', filters)}>PDF</button>
        </span>
      </div>
      {issues.length === 0 ? (
        <Empty>{tr('Нет предписаний по выбранным условиям.')}</Empty>
      ) : (
        <div className="space-y-1">
          {issues.map((i) => (
            <button key={i.id} onClick={() => { setOpenId(i.id); if (i.longitude !== null) requestFlyTo({ issueId: i.id }); }}
              className="block w-full rounded-md border border-bg-border px-2.5 py-2 text-left hover:border-accent-teal/60">
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">№{i.number}</span>
                <StatusBadge status={i.status} />
                {i.priority === 'critical' || i.priority === 'high' ? (
                  <span className="text-[10px] font-semibold text-red-400">{PRIORITY_LABELS[i.priority]}</span>
                ) : null}
                {i.attachments_count > 0 && <span className="ml-auto text-[10px] text-text-muted">📎{i.attachments_count}</span>}
              </div>
              <div className="mt-0.5 truncate text-sm">{i.title}</div>
              <div className="text-[11px] text-text-muted">
                {i.assignee_name ?? tr('не назначен')}
                {i.due_date && ` · ${tr('до {d}', { d: new Date(i.due_date).toLocaleDateString(locale()) })}`}
                {i.overdue && <span className="text-red-400"> {tr('· просрочено')}</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
