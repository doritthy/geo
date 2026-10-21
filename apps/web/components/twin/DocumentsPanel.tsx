'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import { DOC_TYPE_LABELS, type DocType, type DocumentDetail, type DocumentSummary } from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Icons, Input, Select, formatBytes } from './ui';

function NewDocumentForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const selection = useTwinStore((s) => s.selection);
  const bumpData = useTwinStore((s) => s.bumpData);
  const [title, setTitle] = useState('');
  const [docType, setDocType] = useState<DocType>('rd');
  const [code, setCode] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [link, setLink] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const element = selection?.kind === 'element' ? selection : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setSaving(true);
    setError(null);
    const form = new FormData();
    form.append('title', title || file.name);
    form.append('doc_type', docType);
    if (code) form.append('code', code);
    if (element && link && element.assetId) {
      form.append('asset_id', element.assetId);
      if (element.globalId) form.append('element_global_id', element.globalId);
    }
    form.append('file', file);
    try {
      await twinApi.createDocument(projectId, form);
      bumpData();
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить документ');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-lg border border-bg-border bg-bg-panel2/60 p-3">
      <Field label="Файл">
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="w-full text-xs text-text-secondary" required />
      </Field>
      <Field label="Наименование">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={file?.name ?? 'Раздел КЖ, лист 3'} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Тип">
          <Select value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
            <option value="pd">ПД — проектная</option>
            <option value="rd">РД — рабочая</option>
            <option value="other">Прочее</option>
          </Select>
        </Field>
        <Field label="Шифр / марка">
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="КЖ-01" />
        </Field>
      </div>
      {element && (
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input type="checkbox" checked={link} onChange={(e) => setLink(e.target.checked)} />
          Привязать к выбранному элементу ({element.title || element.globalId})
        </label>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className="flex gap-2">
        <Button variant="primary" type="submit" disabled={saving || !file}>{saving ? 'Загрузка…' : 'Загрузить'}</Button>
        <Button type="button" onClick={onDone}>Отмена</Button>
      </div>
    </form>
  );
}

function DocumentCard({ summary, onChanged }: { summary: DocumentSummary; onChanged: () => void }) {
  const selection = useTwinStore((s) => s.selection);
  const bumpData = useTwinStore((s) => s.bumpData);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) twinApi.getDocument(summary.id).then(setDetail);
  }, [open, summary.id]);

  async function addVersion(file: File) {
    const comment = prompt('Комментарий к новой версии (необязательно)') ?? '';
    const form = new FormData();
    form.append('file', file);
    if (comment) form.append('comment', comment);
    setBusy(true);
    try {
      setDetail(await twinApi.addDocumentVersion(summary.id, form));
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function linkSelected() {
    if (selection?.kind !== 'element' || !selection.assetId) return;
    await twinApi.linkDocument(summary.id, selection.assetId, selection.globalId ?? null);
    setDetail(await twinApi.getDocument(summary.id));
    bumpData();
  }

  async function remove() {
    if (!confirm(`Удалить документ «${summary.title}» со всеми версиями?`)) return;
    await twinApi.deleteDocument(summary.id);
    bumpData();
    onChanged();
  }

  const latest = summary.latest_version;
  return (
    <div className="rounded-md border border-bg-border">
      <button onClick={() => setOpen(!open)} className="block w-full px-2.5 py-2 text-left">
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-bg-panel2 px-1.5 text-[10px] font-semibold text-accent-teal">{DOC_TYPE_LABELS[summary.doc_type]}</span>
          <span className="truncate text-sm">{summary.title}</span>
        </div>
        <div className="mt-0.5 text-[11px] text-text-muted">
          {summary.code && `${summary.code} · `}
          {latest ? `версия ${latest.version} · ${formatBytes(latest.size_bytes)}` : 'без файла'}
        </div>
      </button>
      {open && (
        <div className="space-y-2 border-t border-bg-border px-2.5 py-2">
          {detail?.versions
            .slice()
            .reverse()
            .map((v) => (
              <div key={v.id} className="flex items-center gap-2 text-xs">
                <span className="w-8 text-text-muted">v{v.version}</span>
                <span className="min-w-0 flex-1 truncate" title={v.comment ?? ''}>
                  {v.filename}
                  {v.comment && <span className="text-text-muted"> — {v.comment}</span>}
                </span>
                <button className="text-text-secondary hover:text-accent-teal" title="Скачать" onClick={() => twinApi.downloadDocumentVersion(v.id, v.filename)}>
                  {Icons.download}
                </button>
              </div>
            ))}
          {detail && (
            <div className="text-[11px] text-text-muted">
              Привязки: {detail.links.length === 0 ? 'нет' : detail.links.map((l) => l.element_global_id ?? 'вся модель').join(', ')}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <label className="cursor-pointer rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary">
              {busy ? 'Загрузка…' : 'Новая версия'}
              <input type="file" className="hidden" onChange={(e) => e.target.files?.[0] && addVersion(e.target.files[0])} />
            </label>
            {selection?.kind === 'element' && <Button onClick={linkSelected}>Привязать к элементу</Button>}
            <Button variant="danger" onClick={remove}>Удалить</Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DocumentsPanel({ projectId }: { projectId: string }) {
  const selection = useTwinStore((s) => s.selection);
  const [q, setQ] = useState('');
  const [docType, setDocType] = useState<DocType | ''>('');
  const [onlySelected, setOnlySelected] = useState(false);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    const gid = onlySelected && selection?.kind === 'element' ? selection.globalId : undefined;
    twinApi.listDocuments(projectId, { q: q || undefined, doc_type: docType || undefined, global_id: gid }).then(setDocs);
  }, [projectId, q, docType, onlySelected, selection]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <div className="space-y-3">
      {adding ? (
        <NewDocumentForm projectId={projectId} onDone={() => { setAdding(false); load(); }} />
      ) : (
        <Button variant="primary" onClick={() => setAdding(true)}>+ Загрузить документ</Button>
      )}
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по названию, шифру, файлу…" />
      <div className="flex gap-2">
        <Select value={docType} onChange={(e) => setDocType(e.target.value as DocType | '')}>
          <option value="">Все типы</option>
          <option value="pd">ПД</option>
          <option value="rd">РД</option>
          <option value="other">Прочее</option>
        </Select>
      </div>
      {selection?.kind === 'element' && (
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />
          Только для выбранного элемента
        </label>
      )}
      {docs.length === 0 ? <Empty>Документов не найдено.</Empty> : docs.map((d) => <DocumentCard key={d.id} summary={d} onChanged={load} />)}
    </div>
  );
}
