'use client';

import { useEffect, useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { DOC_TYPE_LABELS, type BimElementDetail } from '@/lib/twin/types';
import { Button, Icons } from './ui';
import { tr } from '@/lib/i18n';

function Row({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined || v === '') return null;
  return (
    <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2 border-b border-bg-border/60 py-1 text-xs">
      <span className="break-words text-text-secondary">{k}</span>
      <span className="break-words text-text-primary">{typeof v === 'boolean' ? (v ? tr('Да') : tr('Нет')) : String(v)}</span>
    </div>
  );
}

/** Right-hand drawer: properties of whatever is selected in the scene. */
export default function PropertiesPanel() {
  const selection = useTwinStore((s) => s.selection);
  const setSelection = useTwinStore((s) => s.setSelection);
  const annotations = useTwinStore((s) => s.annotations);
  const setPanel = useTwinStore((s) => s.setPanel);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const dataTick = useTwinStore((s) => s.dataTick);
  const [detail, setDetail] = useState<BimElementDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    if (selection?.kind === 'element' && selection.assetId && selection.globalId) {
      twinApi
        .getElement(selection.assetId, selection.globalId)
        .then(setDetail)
        .catch(() => setError(tr('Элемент не найден в индексе модели')));
    }
  }, [selection, dataTick]);

  if (!selection) return null;
  const note = selection.kind === 'annotation' ? annotations.find((a) => a.id === selection.annotationId) : null;

  return (
    <aside className="absolute bottom-0 right-0 top-0 z-20 flex w-full max-w-sm flex-col border-l border-bg-border bg-bg-panel/95 backdrop-blur sm:bottom-auto sm:right-3 sm:top-3 sm:max-h-[calc(100%-1.5rem)] sm:rounded-xl sm:border">
      <div className="flex items-center justify-between border-b border-bg-border px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">
            {detail?.name || note?.title || selection.title || tr('Свойства')}
          </div>
          <div className="text-[11px] text-text-muted">
            {selection.kind === 'element' ? detail?.ifc_type ?? tr('BIM-элемент') : selection.kind === 'feature' ? tr('Объект ГИС') : tr('Замечание')}
          </div>
        </div>
        <button onClick={() => setSelection(null)} className="text-text-secondary hover:text-text-primary" aria-label={tr('Закрыть')}>
          {Icons.close}
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {error && <div className="text-xs text-red-300">{error}</div>}

        {detail && (
          <>
            <div>
              <Row k="GlobalId" v={detail.global_id} />
              <Row k={tr('Класс')} v={detail.ifc_type} />
              <Row k={tr('Этаж / уровень')} v={detail.storey} />
              {Object.entries(detail.properties)
                .filter(([k]) => k !== 'psets')
                .map(([k, v]) => <Row key={k} k={k} v={v} />)}
            </div>
            {Object.entries(detail.properties.psets ?? {}).map(([pset, props]) => (
              <div key={pset}>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent-teal">{pset}</div>
                {Object.entries(props).map(([k, v]) => <Row key={k} k={k} v={typeof v === 'object' ? JSON.stringify(v) : v} />)}
              </div>
            ))}
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{tr('Документы')}</div>
              {detail.documents.length === 0 ? (
                <div className="text-xs text-text-muted">{tr('Нет привязанных документов')}</div>
              ) : (
                detail.documents.map((d) => (
                  <div key={d.id} className="flex items-center justify-between gap-2 py-1 text-xs">
                    <span className="truncate">
                      <span className="mr-1 rounded bg-bg-panel2 px-1 text-[10px] text-text-secondary">{DOC_TYPE_LABELS[d.doc_type]}</span>
                      {d.code ? `${d.code} · ` : ''}{d.title}
                    </span>
                    {d.latest_version && (
                      <button
                        title={tr('Скачать')}
                        className="text-text-secondary hover:text-accent-teal"
                        onClick={() => twinApi.downloadDocumentVersion(d.latest_version!.id, d.latest_version!.filename)}
                      >
                        {Icons.download}
                      </button>
                    )}
                  </div>
                ))
              )}
              <Button className="mt-2" onClick={() => setPanel('documents')}>{tr('Привязать документ')}</Button>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{tr('Замечания')}</div>
              {detail.annotations.length === 0 ? (
                <div className="text-xs text-text-muted">{tr('Нет замечаний')}</div>
              ) : (
                detail.annotations.map((a) => (
                  <button key={a.id} onClick={() => requestFlyTo({ annotationId: a.id })} className="block w-full py-1 text-left text-xs hover:text-accent-teal">
                    {a.title}
                  </button>
                ))
              )}
            </div>
          </>
        )}

        {selection.kind === 'feature' && selection.properties && (
          <div>
            {Object.entries(selection.properties).map(([k, v]) => (
              <Row key={k} k={k} v={typeof v === 'object' ? JSON.stringify(v) : v} />
            ))}
          </div>
        )}

        {note && (
          <div className="space-y-2 text-sm">
            {note.body && <p className="whitespace-pre-wrap text-text-primary">{note.body}</p>}
            <div className="text-xs text-text-muted">
              {note.author_name ?? '—'} · {new Date(note.created_at).toLocaleString('ru-RU')}
            </div>
            {note.element_global_id && <Row k={tr('Элемент')} v={note.element_global_id} />}
            <Row k={tr('Координаты')} v={`${note.latitude.toFixed(6)}, ${note.longitude.toFixed(6)}, H ${note.height.toFixed(2)} м`} />
          </div>
        )}
      </div>
    </aside>
  );
}
