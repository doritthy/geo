'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth';

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(isAuthenticated() ? '/projects' : '/login');
  }, [router]);

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-bg text-text-secondary">
      Loading…
    </div>
  );
}
