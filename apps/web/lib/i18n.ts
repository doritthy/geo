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

export function tr(text: string): string {
  if (current === 'kk') return KK[text] ?? text;
  return text;
}

export function setLang(lang: Lang): void {
  document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
  window.location.reload();
}
