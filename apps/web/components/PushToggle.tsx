'use client';

import { useEffect, useState } from 'react';
import { request } from '@/lib/api';
import { tr } from '@/lib/i18n';

/** Bell in the header: subscribes this browser to Web Push (issue
 * assignments and status changes). Hidden when the server has no VAPID keys
 * or the browser lacks Push API support (iOS: only as an installed PWA). */
export default function PushToggle() {
  const [key, setKey] = useState<string | null>(null);
  const [sub, setSub] = useState<PushSubscription | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    request<{ enabled: boolean; public_key: string | null }>('/api/push/config')
      .then(async (c) => {
        if (!c.enabled || !c.public_key) return;
        setKey(c.public_key);
        const reg = await navigator.serviceWorker.getRegistration();
        setSub((await reg?.pushManager.getSubscription()) ?? null);
      })
      .catch(() => {});
  }, []);

  if (!key) return null;

  async function toggle() {
    setBusy(true);
    try {
      if (sub) {
        await request(`/api/push/subscriptions?endpoint=${encodeURIComponent(sub.endpoint)}`, { method: 'DELETE' });
        await sub.unsubscribe();
        setSub(null);
        return;
      }
      if ((await Notification.requestPermission()) !== 'granted') return;
      const reg = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register('/sw.js'));
      await navigator.serviceWorker.ready;
      const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key! });
      const json = s.toJSON();
      await request('/api/push/subscriptions', { method: 'POST', body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }) });
      setSub(s);
    } catch (err) {
      console.error('Push subscription failed', err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={sub ? tr('Отключить уведомления на этом устройстве') : tr('Включить уведомления о предписаниях')}
      className={`rounded-md border px-2 py-1.5 ${sub ? 'border-accent-teal text-accent-teal' : 'border-bg-border text-text-secondary hover:text-text-primary'}`}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        {!sub && <path d="M2 2l20 20" />}
      </svg>
    </button>
  );
}
