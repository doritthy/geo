import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin', 'cyrillic'], variable: '--font-inter', display: 'swap' });

export const metadata: Metadata = {
  title: 'Цифровой двойник строительства',
  description: 'BIM, облака точек и фотограмметрия в единой геопривязанной 3D-сцене: контроль, анализ и управление строительством.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <body className="min-h-screen bg-bg font-sans text-text-primary antialiased">{children}</body>
    </html>
  );
}
