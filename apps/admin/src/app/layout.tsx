import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { JanuaProvider } from '@janua/nextjs-sdk';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: 'AutoSwarm Admin',
  description: 'Administration panel for AutoSwarm Office',
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
          config={{ baseURL: process.env.NEXT_PUBLIC_JANUA_ISSUER_URL ?? '' }}
        >
          {children}
        </JanuaProvider>
      </body>
    </html>
  );
}
