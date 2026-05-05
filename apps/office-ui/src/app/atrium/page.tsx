/**
 * /atrium — Atrium launchpad page.
 *
 * Full grid of platform tiles for first-time discovery and deep-link
 * sharing. This is the ONLY Next.js route the Atrium owns; everything
 * else happens via the AtriumOverlay rendered inside the office shell.
 *
 * Behaviour: clicking a tile opens the window in the Atrium AND
 * navigates back to /office so the operator lands inside the office
 * with the window already open. This way bookmarks like
 * /atrium#karafiel make sense as deep links.
 */

import type { Metadata } from 'next';
import { AtriumLaunchpad } from './AtriumLaunchpad';

export const metadata: Metadata = {
  title: 'Atrium — MADFAM Ecosystem | Selva',
  description:
    'Welcome to the Atrium — the central space inside the Selva office where every MADFAM platform converges as a draggable window.',
};

export default function AtriumLaunchpadPage() {
  return <AtriumLaunchpad />;
}
