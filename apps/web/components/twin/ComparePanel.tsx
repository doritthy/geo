'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import type { BimElementSummary } from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Select } from './ui';
import { tr } from '@/lib/i18n';

const GROUPS: { key: 'added' | 'removed' | 'modified_geometry' | 'modified_properties'; label: string; color: string }[] = [
  { key: 'added', label: tr('Добавлено'), color: '#22C55E' },
  { key: 'removed', label: tr('Удалено'), color: '#EF4444' },
  { key: 'modified_geometry', label: tr('Изменена геометрия'), color: '#F97316' },
  { key: 'modified_properties', label: tr('Изменены свойства'), color: '#EAB308' },
];

/** Version comparison of two BIM models by IFC GlobalId, coloured in 3D. */
export default function ComparePanel() {
  const assets = useTwinStore((s) => s.assets);
  const bim = useMemo(() => assets.filter((a) => a.kind === 'bim'), [assets]);
  const compare = useTwinStore((s) => s.compare);
  const setCompare = useTwinStore((s) => s.setCompare);
  const setSelection = useTwinStore((s) => s.setSelection);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [baseId, setBaseId] = useState('');
  const [otherId, setOtherId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>('added');

  useEffect(() => {
    if (bim.length >= 2 && !baseId && !otherId) {
      // Default: the two latest versions of the most recent model group.
      const latest = bim[bim.length - 1];
      const group = bim.filter((a) => a.version_group === latest.version_group).sort((a, b) => a.version - b.version);
      if (group.length >= 2) {
        setBaseId(group[group.length - 2].id);
        setOtherId(group[group.length - 1].id);
      } else {
        setBaseId(bim[bim.length - 2].id);
        setOtherId(latest.id);
      }
    }
  }, [bim, baseId, otherId]);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const result = await twinApi.compare(baseId, otherId);
      setCompare({
        ...result,
        baseName: bim.find((a) => a.id === baseId)?.name ?? '',
        otherName: bim.find((a) => a.id === otherId)?.name ?? '',
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Сравнение не удалось'));
    } finally {
      setLoading(false);
    }
  }

  async function open(item: BimElementSummary, removed: boolean) {
    const assetId = removed ? compare!.base_asset_id : compare!.other_asset_id;
    setSelection({ kind: 'element', assetId, globalId: item.global_id, title: item.name ?? item.ifc_type });
    const d = await twinApi.getElement(assetId, item.global_id);
    if (d.bbox) requestFlyTo({ assetId, bbox: d.bbox });
  }

  if (bim.length < 2) {
    return <Empty>{tr('Для сравнения загрузите вторую версию BIM-модели (при загрузке выберите «Новая версия модели»).')}</Empty>;
  }

  const label = (id: string) => {
    const a = bim.find((x) => x.id === id);
    return a ? `${a.name} · v${a.version}` : '';
  };

  return (
    <div className="space-y-3">
      <Field label={tr('Базовая версия')}>
        <Select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
          {bim.map((a) => <option key={a.id} value={a.id}>{label(a.id)}</option>)}
        </Select>
      </Field>
      <Field label={tr('Сравнить с')}>
        <Select value={otherId} onChange={(e) => setOtherId(e.target.value)}>
          {bim.map((a) => <option key={a.id} value={a.id}>{label(a.id)}</option>)}
        </Select>
      </Field>
      <div className="flex gap-2">
        <Button variant="primary" onClick={run} disabled={loading || !baseId || !otherId || baseId === otherId}>
          {loading ? tr('Сравнение…') : tr('Сравнить')}
        </Button>
        {compare && <Button onClick={() => setCompare(null)}>{tr('Сбросить')}</Button>}
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}

      {compare && (
        <div className="space-y-2">
          <div className="text-xs text-text-muted">
            Без изменений: {compare.counts.unchanged}
            {compare.truncated && tr(' · списки усечены')}
          </div>
          {GROUPS.map((g) => (
            <div key={g.key} className="rounded-md border border-bg-border">
              <button onClick={() => setOpenGroup(openGroup === g.key ? null : g.key)} className="flex w-full items-center gap-2 px-2.5 py-2 text-sm">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: g.color }} />
                {g.label}
                <span className="ml-auto text-text-muted">{compare.counts[g.key]}</span>
              </button>
              {openGroup === g.key && compare[g.key].length > 0 && (
                <div className="max-h-60 overflow-y-auto border-t border-bg-border">
                  {compare[g.key].map((item) => (
                    <button
                      key={item.global_id}
                      onClick={() => open(item, g.key === 'removed')}
                      className="block w-full px-2.5 py-1 text-left text-xs hover:bg-bg-panel2"
                    >
                      {item.name || tr('(без имени)')} <span className="text-text-muted">· {item.ifc_type.replace(/^Ifc/, '')}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
