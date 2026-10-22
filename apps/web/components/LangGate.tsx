'use client';

import { useEffect, useState } from 'react';

/** Server HTML is always Russian; for other languages render only after mount
 * so translated client output never mismatches during hydration. */
export default function LangGate({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? <>{children}</> : null;
}
