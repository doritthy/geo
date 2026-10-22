'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import type { BimElementSummary } from '@/lib/twin/types';
import { Button, Empty, Field, Input, Select } from './ui';
import { tr } from '@/lib/i18n';

/** Element search over the BIM index: by name / GlobalId / class / storey.
 * Results can be highlighted in 3D; clicking one selects and flies to it. */
export default function SearchPanel() {
  const assets = useTwinStore((s) => s.assets);
  const bimAssets = useMemo(() => assets.filter((a) => a.kind === 'bim'), [assets]);
  const setSelection = useTwinStore((s) => s.setSelection);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const setHighlight = useTwinStore((s) => s.setHighlight);
  const highlight = useTwinStore((s) => s.highlight);

  const [assetId, setAssetId] = useState<string>('');
  const [q, setQ] = useState('');
  const [ifcType, setIfcType] = useState('');
  const [storey, setStorey] = useState('');
  const [items, setItems] = useState<BimElementSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!assetId && bimAssets.length) setAssetId(bimAssets[bimAssets.length - 1].id);
  }, [bimAssets, assetId]);

  const asset = bimAssets.find((a) => a.id === assetId);

  useEffect(() => {
    if (!assetId) return;
    setLoading(true);
    const t = setTimeout(() => {
      twinApi
        .listElements(assetId, { q: q || undefined, ifc_type: ifcType || undefined, storey: storey || undefined, limit: 200 })
        .then((page) => {
          setItems(page.items);
          setTotal(page.total);
        })
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [assetId, q, ifcType, storey]);

  async function open(item: BimElementSummary) {
    setSelection({ kind: 'element', assetId, globalId: item.global_id, title: item.name ?? item.ifc_type });
    const detail = await twinApi.getElement(assetId, item.global_id);
    if (detail.bbox) requestFlyTo({ assetId, bbox: detail.bbox });
  }

  if (bimAssets.length === 0) return <Empty>{tr('Поиск доступен после загрузки BIM-модели.')}</Empty>;

  return (
    <div className="space-y-3">
      <Field label={tr('Модель')}>
        <Select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
          {bimAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} (v{a.version})
            </option>
          ))}
        </Select>
      </Field>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr('Название, GlobalId, класс…')} />
      <div className="grid grid-cols-2 gap-2">
        <Select value={ifcType} onChange={(e) => setIfcType(e.target.value)}>
          <option value="">{tr('Все классы')}</option>
          {Object.keys(asset?.stats.ifc_types ?? {}).map((t) => (
            <option key={t} value={t}>{t.replace(/^Ifc/, '')}</option>
          ))}
        </Select>
        <Select value={storey} onChange={(e) => setStorey(e.target.value)}>
          <option value="">{tr('Все этажи')}</option>
          {Object.keys(asset?.stats.storeys ?? {}).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
      </div>
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>{loading ? tr('Поиск…') : `Найдено: ${total}${total > items.length ? ` (показано ${items.length})` : ''}`}</span>
        {highlight ? (
          <Button variant="ghost" onClick={() => setHighlight(null)}>{tr('Снять подсветку')}</Button>
        ) : (
          <Button variant="ghost" onClick={() => setHighlight(items)} disabled={!items.length}>{tr('Подсветить')}</Button>
        )}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <button
            key={item.global_id}
            onClick={() => open(item)}
            className="block w-full rounded-md border border-bg-border px-2.5 py-1.5 text-left hover:border-accent-teal/60"
          >
            <div className="truncate text-sm">{item.name || tr('(без имени)')}</div>
            <div className="flex gap-2 text-[11px] text-text-muted">
              <span>{item.ifc_type.replace(/^Ifc/, '')}</span>
              {item.storey && <span>{item.storey}</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
