import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { UpgradeModal } from '../UpgradeModal';

const startCheckoutMock = vi.fn();
vi.mock('@/hooks/useCheckout', () => ({
  useCheckout: () => ({ loading: false, startCheckout: startCheckoutMock }),
}));

vi.mock('@/hooks/useFocusTrap', () => ({
  useFocusTrap: () => ({ current: null }),
}));

describe('UpgradeModal', () => {
  beforeEach(() => startCheckoutMock.mockReset());

  it('renders nothing when closed', () => {
    const { container } = render(<UpgradeModal open={false} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the 402 message and starts checkout on the upgrade CTA', () => {
    render(
      <UpgradeModal
        open
        onClose={() => {}}
        message="You've hit today's compute budget."
        suggestedTier="professional"
      />,
    );

    expect(screen.getByText(/hit today.s compute budget/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /upgrade my plan/i }));
    expect(startCheckoutMock).toHaveBeenCalledWith('professional');
  });

  it('offers a link to all plans and a close control', () => {
    const onClose = vi.fn();
    render(<UpgradeModal open onClose={onClose} />);

    expect(screen.getByRole('link', { name: /see all plans/i })).toHaveAttribute(
      'href',
      '/pricing',
    );
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
