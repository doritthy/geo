import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { cookies } from 'next/headers';
import ServiceWorker from '@/components/ServiceWorker';
import LangGate from '@/components/LangGate';

const inter = Inter({ subsets: ['latin', 'cyrillic'], variable: '--font-inter', display: 'swap' });

export const metadata: Metadata = {
  title: 'Цифровой двойник строительства',
  description: 'BIM, облака точек и фотограмметрия в единой геопривязанной 3D-сцене: контроль, анализ и управление строительством.',
  manifest: '/manifest.webmanifest',
  icons: { icon: '/icons/icon-192.png', apple: '/icons/icon-192.png' },
  appleWebApp: { capable: true, title: 'Двойник', statusBarStyle: 'black-translucent' },
};

export const viewport: Viewport = {
  themeColor: '#0B0F19',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const lang = cookies().get('lang')?.value === 'kk' ? 'kk' : 'ru';
  return (
    <html lang={lang} className={inter.variable}>
      <body className="min-h-screen bg-bg font-sans text-text-primary antialiased">
        {lang === 'ru' ? children : <LangGate>{children}</LangGate>}
        <ServiceWorker />
      </body>
    </html>
  );
}
