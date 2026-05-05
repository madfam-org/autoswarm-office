/**
 * Internal-only preview route for the Jumanji easter egg.
 * Renders all four device states + reduced-motion variant.
 * Not linked from anywhere in the app — known URL only.
 */
import { JumanjiDeviceStates } from '@/components/easter-eggs/JumanjiDeviceStates';

export const metadata = {
  title: 'Jumanji Device — Preview',
  robots: { index: false, follow: false },
};

export default function JumanjiPreviewPage() {
  return <JumanjiDeviceStates />;
}
