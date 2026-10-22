'use client';

import { getLang, setLang, type Lang } from '@/lib/i18n';

const LANGS: { key: Lang; label: string }[] = [
  { key: 'ru', label: 'RU' },
  { key: 'kk', label: 'KZ' },
];

/** RU / KZ toggle; switching stores the cookie and reloads the page. */
export default function LangSwitch() {
  const cur = getLang();
  return (
    <div className="flex rounded-md border border-bg-border p-0.5 text-[11px]">
      {LANGS.map((l) => (
        <button
          key={l.key}
          onClick={() => l.key !== cur && setLang(l.key)}
          className={`rounded px-1.5 py-0.5 ${l.key === cur ? 'bg-bg-panel2 text-text-primary' : 'text-text-muted hover:text-text-primary'}`}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
