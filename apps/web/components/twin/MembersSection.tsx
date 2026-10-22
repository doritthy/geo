'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { request, ApiError } from '@/lib/api';
import { getStoredUser } from '@/lib/auth';
import { Button, ErrorBox, Input, Select } from './ui';

interface OrgUser { id: string; email: string; full_name: string | null; role: string }
interface Membership { user_id: string; email: string; full_name: string | null; role: string }

const PROJECT_ROLES: Record<string, string> = { owner: 'Владелец', editor: 'Редактор', viewer: 'Просмотр' };
const ORG_ROLES: Record<string, string> = { admin: 'Администратор', geologist: 'Специалист', viewer: 'Наблюдатель' };

/** Project members and (for org admins) organisation user accounts. */
export default function MembersSection({ projectId }: { projectId: string }) {
  const me = getStoredUser();
  const isAdmin = me?.role === 'admin';
  const [members, setMembers] = useState<Membership[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [addEmail, setAddEmail] = useState('');
  const [addRole, setAddRole] = useState('editor');
  const [nu, setNu] = useState({ email: '', full_name: '', password: '', role: 'geologist' });
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setMembers(await request<Membership[]>(`/api/projects/${projectId}/memberships`));
    if (isAdmin) setUsers(await request<OrgUser[]>('/api/organization/users'));
  }, [projectId, isAdmin]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setError(null);
    setInfo(null);
    try {
      await fn();
      setInfo(ok);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Ошибка');
    }
  }

  function addMember(e: FormEvent) {
    e.preventDefault();
    run(() => request(`/api/projects/${projectId}/members`, { method: 'POST', body: JSON.stringify({ email: addEmail, role: addRole }) }), 'Участник добавлен')
      .then(() => setAddEmail(''));
  }

  function createUser(e: FormEvent) {
    e.preventDefault();
    run(() => request('/api/organization/users', { method: 'POST', body: JSON.stringify({ ...nu, full_name: nu.full_name || null }) }),
      `Пользователь ${nu.email} создан — сообщите ему пароль`).then(() => setNu({ email: '', full_name: '', password: '', role: 'geologist' }));
  }

  const notMembers = users.filter((u) => !members.some((m) => m.user_id === u.id));

  return (
    <div className="space-y-4 border-t border-bg-border pt-4">
      <div>
        <div className="mb-2 text-sm font-semibold">Участники проекта</div>
        <div className="space-y-1">
          {members.map((m) => (
            <div key={m.user_id} className="flex items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate">{m.full_name || m.email}</span>
              <Select value={m.role} className="w-32"
                onChange={(e) => run(() => request(`/api/projects/${projectId}/members`, { method: 'POST', body: JSON.stringify({ email: m.email, role: e.target.value }) }), 'Роль изменена')}>
                {Object.entries(PROJECT_ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
              {m.user_id !== me?.id && (
                <button className="text-text-muted hover:text-red-300" title="Убрать из проекта"
                  onClick={() => run(() => request(`/api/projects/${projectId}/members/${m.user_id}`, { method: 'DELETE' }), 'Участник удалён')}>
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
        <form onSubmit={addMember} className="mt-2 flex gap-2">
          {isAdmin && notMembers.length ? (
            <Select value={addEmail} onChange={(e) => setAddEmail(e.target.value)} required>
              <option value="">Пользователь…</option>
              {notMembers.map((u) => <option key={u.id} value={u.email}>{u.full_name || u.email}</option>)}
            </Select>
          ) : (
            <Input value={addEmail} onChange={(e) => setAddEmail(e.target.value)} placeholder="email коллеги" type="email" required />
          )}
          <Select value={addRole} onChange={(e) => setAddRole(e.target.value)} className="w-32">
            {Object.entries(PROJECT_ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Button type="submit">Добавить</Button>
        </form>
      </div>

      {isAdmin && (
        <div>
          <div className="mb-2 text-sm font-semibold">Пользователи организации</div>
          <div className="mb-2 space-y-0.5 text-xs text-text-secondary">
            {users.map((u) => (
              <div key={u.id} className="flex justify-between gap-2">
                <span className="truncate">{u.full_name || u.email} <span className="text-text-muted">{u.email}</span></span>
                <span className="shrink-0">{ORG_ROLES[u.role] ?? u.role}</span>
              </div>
            ))}
          </div>
          <form onSubmit={createUser} className="space-y-2 rounded-md bg-bg-panel2/50 p-2">
            <div className="grid grid-cols-2 gap-2">
              <Input value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} placeholder="ФИО" />
              <Input value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} placeholder="email" type="email" required />
              <Input value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} placeholder="пароль (от 8 символов)" minLength={8} required />
              <Select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
                {Object.entries(ORG_ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            </div>
            <Button type="submit" variant="primary">Создать пользователя</Button>
          </form>
        </div>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}
      {info && <div className="text-xs text-accent-teal">{info}</div>}
    </div>
  );
}
