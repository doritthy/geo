'use client';

// Small shared UI primitives + inline icons for the twin workspace.

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';

export const inputCls =
  'w-full rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-1.5 text-sm text-text-primary outline-none focus:border-accent-teal';

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${props.className ?? ''}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${inputCls} ${props.className ?? ''}`} />;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-text-secondary">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-text-muted">{hint}</span>}
    </label>
  );
}

export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }) {
  const styles = {
    primary: 'bg-accent-teal text-bg hover:bg-accent-teal/90 font-semibold',
    secondary: 'border border-bg-border text-text-secondary hover:text-text-primary hover:border-text-muted',
    danger: 'border border-red-900/60 text-red-300 hover:bg-red-950/40',
    ghost: 'text-text-secondary hover:text-text-primary',
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-md px-3 py-1.5 text-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function IconButton({
  active,
  title,
  children,
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      title={title}
      aria-label={title}
      {...props}
      className={`flex h-9 w-9 items-center justify-center rounded-md transition ${
        active ? 'bg-accent-teal text-bg' : 'text-text-secondary hover:bg-bg-panel2 hover:text-text-primary'
      } ${className}`}
    >
      {children}
    </button>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-xs text-red-300">{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-bg-border p-4 text-center text-xs text-text-muted">{children}</div>;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} Б`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} КБ`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} МБ`;
  return `${(n / 1024 ** 3).toFixed(2)} ГБ`;
}

export function formatNumber(n: number | undefined): string {
  return n === undefined ? '—' : n.toLocaleString('ru-RU');
}

const svg = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {d}
  </svg>
);

export const Icons = {
  select: svg(<path d="M5 3l14 8-6 2-2 6z" />),
  point: svg(<><circle cx="12" cy="10" r="3" /><path d="M12 21s-7-6.5-7-11a7 7 0 0114 0c0 4.5-7 11-7 11z" /></>),
  distance: svg(<><path d="M3 17L17 3l4 4L7 21z" /><path d="M7 13l2 2M10 10l2 2M13 7l2 2" /></>),
  area: svg(<path d="M4 7l7-4 9 5-3 11-11 2z" />),
  height: svg(<><path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4" /></>),
  angle: svg(<><path d="M4 20h16M4 20L16 5" /><path d="M10 20a6 6 0 00-1.8-4.3" /></>),
  volume: svg(<><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" /></>),
  annotate: svg(<><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /><path d="M12 7v6M9 10h6" /></>),
  clear: svg(<><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></>),
  layers: svg(<><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>),
  search: svg(<><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>),
  docs: svg(<><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></>),
  compare: svg(<><path d="M8 3v18M16 3v18" /><path d="M3 8h5M16 16h5" /></>),
  settings: svg(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></>),
  eye: svg(<><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" /><circle cx="12" cy="12" r="3" /></>),
  eyeOff: svg(<><path d="M17.9 17.9A10.4 10.4 0 0112 19c-7 0-11-7-11-7a18.5 18.5 0 015.1-5.9M9.9 4.2A9.1 9.1 0 0112 4c7 0 11 7 11 7a18.6 18.6 0 01-2.2 3.2M1 1l22 22" /></>),
  target: svg(<><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="2" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></>),
  section: svg(<><path d="M3 12h18" strokeDasharray="3 2" /><path d="M6 4h12v16H6z" /></>),
  globe: svg(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></>),
  plan: svg(<><path d="M3 3h18v18H3z" /><path d="M3 9h18M9 21V9" /></>),
  cube: svg(<><path d="M12 2l9 5v10l-9 5-9-5V7z" /><path d="M12 22V12M21 7l-9 5-9-5" /></>),
  upload: svg(<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v4h16v-4" /></>),
  close: svg(<path d="M6 6l12 12M18 6L6 18" />),
  menu: svg(<path d="M4 6h16M4 12h16M4 18h16" />),
  chevron: svg(<path d="M9 6l6 6-6 6" />),
  clock: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>),
  download: svg(<><path d="M12 4v12M7 11l5 5 5-5" /><path d="M4 20h16" /></>),
  link: svg(<><path d="M10 13a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1" /><path d="M14 11a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1" /></>),
  trash: svg(<><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></>),
};
