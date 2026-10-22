// Minimal gettext-style i18n: the Russian UI text is the key; `tr()` returns
// the Kazakh translation when the interface language is kk.
//
// The language is chosen once per page load (cookie `lang`, set by
// setLang(), which reloads the page), so module-level label tables and
// components translate consistently without a reactive context. For kk the
// root layout renders client-side only (see LangGate) to avoid SSR mismatch.

import { KK } from './i18n.kk';

export type Lang = 'ru' | 'kk';

function readLang(): Lang {
  if (typeof document === 'undefined') return 'ru';
  const m = document.cookie.match(/(?:^|;\s*)lang=(ru|kk)/);
  return (m?.[1] as Lang) ?? 'ru';
}

const current: Lang = readLang();

export function getLang(): Lang {
  return current;
}

/** Translate; `{name}` placeholders are filled from `vars` after lookup. */
export function tr(text: string, vars?: Record<string, string | number>): string {
  let out = current === 'kk' ? KK[text] ?? text : text;
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
  return out;
}

/** Locale for dates and numbers. Kazakhstan uses dd.mm.yyyy and space-grouped
 * numbers in both languages, and browsers' kk-KZ data is patchy (Chromium
 * falls back to m/d/yyyy), so formatting stays ru-RU for now. */
export function locale(): string {
  return 'ru-RU';
}

export function setLang(lang: Lang): void {
  document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
  window.location.reload();
}
