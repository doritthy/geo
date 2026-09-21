'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth';

/** Wraps a page that requires an authenticated session, redirecting to /login otherwise. */
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login');
    }
  }, [router]);

  if (typeof window !== 'undefined' && !isAuthenticated()) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-bg text-text-secondary">
        Redirecting to sign in…
      </div>
    );
  }

  return <>{children}</>;
}
