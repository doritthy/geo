'use client';

import { useEffect, useState } from 'react';
import { request } from '@/lib/api';
import { absoluteUrl, authHeaders } from '@/lib/twin/api';
import { tr } from '@/lib/i18n';

export interface Branding {
  name: string | null;
  color: string | null;
  organization: string;
  logo_url: string | null;
}

let cache: Promise<Branding> | null = null;
let logoCache: { url: string; blob: string } | null = null;
const listeners = new Set<(b: Branding) => void>();

function applyColor(color: string | null) {
  const m = color?.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  const root = document.documentElement;
  if (m) root.style.setProperty('--accent', `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}`);
  else root.style.removeProperty('--accent');
}

/** Organisation branding (white-label), fetched once per page load. */
export function useBranding(): Branding | null {
  const [b, setB] = useState<Branding | null>(null);
  useEffect(() => {
    cache ??= request<Branding>('/api/branding');
    cache.then((v) => { applyColor(v.color); setB(v); }).catch(() => { cache = null; });
    listeners.add(setB);
    return () => { listeners.delete(setB); };
  }, []);
  return b;
}

/** After an admin changes branding: refresh every mounted header. */
export function publishBranding(b: Branding) {
  cache = Promise.resolve(b);
  logoCache = null;
  applyColor(b.color);
  listeners.forEach((l) => l(b));
}

function useLogo(url: string | null): string | null {
  const [src, setSrc] = useState<string | null>(logoCache?.url === url ? logoCache.blob : null);
  useEffect(() => {
    if (!url) return setSrc(null);
    if (logoCache?.url === url) return setSrc(logoCache.blob);
    fetch(absoluteUrl(url), { headers: authHeaders() })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((blob) => { logoCache = { url, blob: URL.createObjectURL(blob) }; setSrc(logoCache.blob); })
      .catch(() => setSrc(null));
  }, [url]);
  return src;
}

/** Logo (or the default gradient mark) + product name for headers. */
export function BrandMark({ fallback, nameClassName = '' }: { fallback: string; nameClassName?: string }) {
  const b = useBranding();
  const logo = useLogo(b?.logo_url ?? null);
  return (
    <>
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt={b?.name ?? tr('Логотип')} className="h-6 max-w-[96px] object-contain" />
      ) : (
        <div className="h-6 w-6 shrink-0 rounded bg-gradient-to-br from-accent-amber to-accent-teal" />
      )}
      <span className={nameClassName}>{b?.name || fallback}</span>
    </>
  );
}
