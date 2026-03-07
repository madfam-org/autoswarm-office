import type { Metadata } from 'next';
import { Inter, Press_Start_2P } from 'next/font/google';
import { JanuaProvider } from '@janua/nextjs-sdk';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
});

const pressStart2P = Press_Start_2P({
  weight: '400',
  subsets: ['latin'],
  variable: '--font-pixel',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'AutoSwarm Office',
  description: 'Gamified multi-agent business orchestration',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${pressStart2P.variable}`}>
      <body className="min-h-screen font-sans">
        <JanuaProvider
          config={{ baseURL: process.env.NEXT_PUBLIC_JANUA_ISSUER_URL ?? '' }}
        >
          {children}
        </JanuaProvider>
      </body>
    </html>
  );
}
