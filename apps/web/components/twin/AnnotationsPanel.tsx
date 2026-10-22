'use client';

import { useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import { Button, Empty, ErrorBox, Field, Icons, Input } from './ui';
import { tr } from '@/lib/i18n';

const COLORS = ['#F5A623', '#EF4444', '#22C55E', '#3B82F6', '#A78BFA'];

export default function AnnotationsPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const annotations = useTwinStore((s) => s.annotations);
  const pending = useTwinStore((s) => s.pendingAnnotation);
  const setPending = useTwinStore((s) => s.setPendingAnnotation);
  const setTool = useTwinStore((s) => s.setTool);
  const tool = useTwinStore((s) => s.tool);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const setSelection = useTwinStore((s) => s.setSelection);
  const bumpData = useTwinStore((s) => s.bumpData);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [color, setColor] = useState(COLORS[0]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!pending || !title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await twinApi.createAnnotation(projectId, {
        longitude: pending.longitude,
        latitude: pending.latitude,
        height: pending.height,
        title: title.trim(),
        body: body.trim() || undefined,
        color,
        asset_id: pending.assetId ?? null,
        element_global_id: pending.globalId ?? null,
      });
      setTitle('');
      setBody('');
      setPending(null);
      bumpData();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось сохранить замечание'));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!confirm(tr('Удалить замечание?'))) return;
    await twinApi.deleteAnnotation(id);
    bumpData();
    onChanged();
  }

  return (
    <div className="space-y-3">
      {pending ? (
        <div className="space-y-2 rounded-lg border border-accent-teal/50 bg-bg-panel2/60 p-3">
          <div className="text-xs text-text-secondary">
            Новая метка · H {pending.height.toFixed(2)} м
            {pending.globalId && <span className="block text-accent-teal">Привязка к элементу {pending.globalId}</span>}
          </div>
          <Field label={tr('Заголовок')}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder={tr('Например: трещина в плите')} />
          </Field>
          <Field label={tr('Комментарий')}>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-1.5 text-sm outline-none focus:border-accent-teal"
            />
          </Field>
          <div className="flex gap-1.5">
            {COLORS.map((c) => (
              <button
                key={c}
                onClick={() => setColor(c)}
                aria-label={c}
                className={`h-6 w-6 rounded-full border-2 ${color === c ? 'border-white' : 'border-transparent'}`}
                style={{ background: c }}
              />
            ))}
          </div>
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className="flex gap-2">
            <Button variant="primary" onClick={save} disabled={saving || !title.trim()}>{tr('Сохранить')}</Button>
            <Button onClick={() => setPending(null)}>{tr('Отмена')}</Button>
          </div>
        </div>
      ) : (
        <Button variant={tool === 'annotate' ? 'primary' : 'secondary'} onClick={() => setTool(tool === 'annotate' ? 'select' : 'annotate')}>
          {tool === 'annotate' ? tr('Кликните по модели…') : tr('+ Добавить метку на модели')}
        </Button>
      )}

      {annotations.length === 0 && !pending && <Empty>{tr('Замечаний пока нет.')}</Empty>}
      <div className="space-y-1">
        {annotations.map((a) => (
          <div key={a.id} className="group flex items-start gap-2 rounded-md border border-bg-border px-2.5 py-2">
            <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: a.color }} />
            <button
              className="min-w-0 flex-1 text-left"
              onClick={() => {
                requestFlyTo({ annotationId: a.id });
                setSelection({ kind: 'annotation', annotationId: a.id });
              }}
            >
              <div className="truncate text-sm">{a.title}</div>
              <div className="text-[11px] text-text-muted">
                {a.author_name ?? '—'} · {new Date(a.created_at).toLocaleDateString('ru-RU')}
                {a.element_global_id && tr(' · элемент')}
              </div>
            </button>
            <button onClick={() => remove(a.id)} className="text-text-muted opacity-0 hover:text-red-300 group-hover:opacity-100" title={tr('Удалить')}>
              {Icons.trash}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
