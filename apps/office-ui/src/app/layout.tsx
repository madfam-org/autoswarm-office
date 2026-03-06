import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { JanuaProvider } from '@janua/nextjs-sdk';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
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
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen font-sans">
        <JanuaProvider
          issuerUrl={process.env.NEXT_PUBLIC_JANUA_ISSUER_URL ?? ''}
          clientId={process.env.NEXT_PUBLIC_JANUA_CLIENT_ID ?? ''}
        >
          {children}
        </JanuaProvider>
      </body>
    </html>
  );
}
