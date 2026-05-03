import type { Metadata } from 'next';
import { HeroSection } from '@/components/landing/HeroSection';
import { FeatureGrid } from '@/components/landing/FeatureGrid';
import { AgentRoster } from '@/components/landing/AgentRoster';
import { HowItWorks } from '@/components/landing/HowItWorks';
import { EcosystemLinks } from '@/components/landing/EcosystemLinks';
import { Footer } from '@/components/landing/Footer';
import { getSiteConfig } from '@/lib/site-config';

const { marketingUrl } = getSiteConfig();

export const metadata: Metadata = {
  title: 'Selva — Your AI Workforce, Alive in a Virtual Office',
  description:
    'Meet your AI team. 10 specialized agents working in a living virtual office — coding, researching, filing, and deploying — with you in full control. Try the live demo.',
  openGraph: {
    title: 'Selva — Your AI Workforce, Alive in a Virtual Office',
    description:
      'Meet your AI team. 10 specialized agents working in a living virtual office with you in full control.',
    url: marketingUrl,
    siteName: 'Selva',
    type: 'website',
  },
};

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-slate-950 scanline-overlay">
      <HeroSection />
      <FeatureGrid />
      <AgentRoster />
      <HowItWorks />
      <EcosystemLinks />
      <Footer />
    </div>
  );
}
