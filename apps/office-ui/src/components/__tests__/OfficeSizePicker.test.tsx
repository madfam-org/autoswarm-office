import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { OfficeSizePicker } from '../OfficeSizePicker';

// jsdom has no canvas 2d context — stub it so the preview effect is a no-op.
beforeAll(() => {
  // @ts-expect-error - test stub
  HTMLCanvasElement.prototype.getContext = () => ({
    fillStyle: '',
    fillRect: () => undefined,
  });
});

describe('OfficeSizePicker', () => {
  it('renders the five size buckets with the first selected', () => {
    render(<OfficeSizePicker onContinue={() => {}} />);
    for (const label of ['1–10', '11–20', '21–50', '51–80', '81–100']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // First bucket is checked (exact name so it doesn't match 11–20 etc).
    const first = screen.getByRole('radio', { name: '✓ 1–10 Starter' });
    expect(first).toHaveAttribute('aria-checked', 'true');
  });

  it('maps size to a suggested tier and updates on selection', () => {
    render(<OfficeSizePicker onContinue={() => {}} />);
    // Default (1–10) → Starter.
    expect(screen.getByText(/Suggested plan for this size/)).toHaveTextContent('Starter');

    fireEvent.click(screen.getByRole('radio', { name: /81–100/ }));
    expect(screen.getByText(/Suggested plan for this size/)).toHaveTextContent('Enterprise');
  });

  it('offers an upgrade CTA for paid tiers, not for Starter', () => {
    const onUpgrade = vi.fn();
    render(<OfficeSizePicker onContinue={() => {}} onUpgrade={onUpgrade} />);

    // Starter (default) → no upgrade CTA.
    expect(screen.queryByText(/Upgrade to/)).not.toBeInTheDocument();

    // Professional bucket → CTA appears and fires with the tier slug.
    fireEvent.click(screen.getByRole('radio', { name: /11–20/ }));
    const cta = screen.getByText(/Upgrade to Professional/);
    fireEvent.click(cta);
    expect(onUpgrade).toHaveBeenCalledWith('professional');
  });

  it('continues with the chosen size id and tier', () => {
    const onContinue = vi.fn();
    render(<OfficeSizePicker onContinue={onContinue} />);
    fireEvent.click(screen.getByRole('radio', { name: /21–50/ }));
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(onContinue).toHaveBeenCalledWith({ sizeId: '21-50', tier: 'professional' });
  });

  it('renders a labeled preview image for accessibility', () => {
    render(<OfficeSizePicker onContinue={() => {}} />);
    expect(
      screen.getByRole('img', { name: /Preview of an office sized for 1–10 people/i }),
    ).toBeInTheDocument();
  });
});
