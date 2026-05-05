import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { EcosystemWindow } from '../EcosystemWindow';
import { useAtriumStore, type AtriumWindow } from '@/stores/atrium-windows';

beforeEach(() => {
  useAtriumStore.getState()._reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

function makeWindow(overrides: Partial<AtriumWindow> = {}): AtriumWindow {
  return {
    slug: 'karafiel',
    url: 'https://app.karafiel.mx',
    title: 'Karafiel',
    variant: 'app',
    state: 'windowed',
    geometry: { x: 100, y: 100, width: 800, height: 600 },
    zIndex: 100,
    openedAt: 1,
    ...overrides,
  };
}

describe('EcosystemWindow', () => {
  it('renders title bar, iframe, and close/min/max buttons', () => {
    const w = makeWindow();
    render(<EcosystemWindow window={w} isFocused={true} />);
    expect(screen.getByTestId('atrium-window-karafiel')).toBeInTheDocument();
    expect(
      screen.getByTestId('atrium-window-karafiel-iframe'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('atrium-window-karafiel-close'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('atrium-window-karafiel-minimize'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('atrium-window-karafiel-maximize'),
    ).toBeInTheDocument();
  });

  it('iframe sandbox includes the spec-required tokens', () => {
    render(<EcosystemWindow window={makeWindow()} isFocused={true} />);
    const iframe = screen.getByTestId(
      'atrium-window-karafiel-iframe',
    ) as HTMLIFrameElement;
    const sandbox = iframe.getAttribute('sandbox') ?? '';
    expect(sandbox).toContain('allow-scripts');
    expect(sandbox).toContain('allow-forms');
    expect(sandbox).toContain('allow-popups');
    expect(sandbox).toContain('allow-same-origin');
  });

  it('renders an admin pill when variant=admin', () => {
    render(
      <EcosystemWindow
        window={makeWindow({ variant: 'admin' })}
        isFocused={true}
      />,
    );
    expect(
      screen.getByTestId('atrium-window-karafiel-admin-pill'),
    ).toBeInTheDocument();
  });

  it('does not render an admin pill for app variant', () => {
    render(<EcosystemWindow window={makeWindow()} isFocused={true} />);
    expect(
      screen.queryByTestId('atrium-window-karafiel-admin-pill'),
    ).not.toBeInTheDocument();
  });

  it('iframe stays mounted (same DOM node) across focus changes', () => {
    // Add to store so focus/render flow works.
    const open = useAtriumStore.getState().open;
    open({ slug: 'a', url: 'https://a', title: 'A' });
    open({ slug: 'b', url: 'https://b', title: 'B' });
    const wA = useAtriumStore.getState().windows.a;
    const wB = useAtriumStore.getState().windows.b;

    const { rerender } = render(
      <>
        <EcosystemWindow window={wA} isFocused={false} />
        <EcosystemWindow window={wB} isFocused={true} />
      </>,
    );
    const iframeABefore = screen.getByTestId('atrium-window-a-iframe');

    // Simulate focus shift: re-render with focus flipped.
    rerender(
      <>
        <EcosystemWindow window={wA} isFocused={true} />
        <EcosystemWindow window={wB} isFocused={false} />
      </>,
    );
    const iframeAAfter = screen.getByTestId('atrium-window-a-iframe');
    // IMPORTANT: same DOM node — iframe is not remounted.
    expect(iframeAAfter).toBe(iframeABefore);
  });

  it('clicking close calls store.close', () => {
    const open = useAtriumStore.getState().open;
    open({ slug: 'k', url: 'u', title: 'K' });
    const w = useAtriumStore.getState().windows.k;
    render(<EcosystemWindow window={w} isFocused={true} />);
    fireEvent.click(screen.getByTestId('atrium-window-k-close'));
    expect(useAtriumStore.getState().windows.k).toBeUndefined();
  });

  it('clicking minimize calls store.minimize and the window stays in DOM (display:none)', () => {
    const open = useAtriumStore.getState().open;
    open({ slug: 'k', url: 'u', title: 'K' });
    const w = useAtriumStore.getState().windows.k;
    const { rerender } = render(<EcosystemWindow window={w} isFocused={true} />);
    fireEvent.click(screen.getByTestId('atrium-window-k-minimize'));
    const updated = useAtriumStore.getState().windows.k;
    expect(updated.state).toBe('minimized');
    rerender(<EcosystemWindow window={updated} isFocused={false} />);
    // Iframe still in the DOM — that's the point of the design.
    expect(screen.getByTestId('atrium-window-k-iframe')).toBeInTheDocument();
    // But the container has display:none.
    const container = screen.getByTestId('atrium-window-k');
    expect(container).toHaveStyle({ display: 'none' });
  });

  it('iframe element has an onError handler wired to the fallback path', () => {
    // jsdom's iframe error event semantics don't reliably reach React's
    // onError synthetic handler (it depends on element-level vs
    // document-level capture, and iframes are non-bubbling for the
    // resource error). Rather than fight that, assert the wiring:
    // the iframe element exists, the fallback is NOT rendered yet,
    // and the component renders the fallback when iframeFailed flips.
    // The flip is driven by `onError={() => setIframeFailed(true)}`
    // — an integration test in Playwright covers the actual error
    // event path end-to-end.
    const w = makeWindow();
    render(<EcosystemWindow window={w} isFocused={true} />);
    expect(
      screen.getByTestId('atrium-window-karafiel-iframe'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('atrium-window-karafiel-fallback'),
    ).not.toBeInTheDocument();
  });

  it('renders the fallback chrome with both CTAs when iframe fails', async () => {
    // We trigger via React's act + direct invocation of the
    // onError handler through the iframe ref to avoid jsdom event
    // semantics. We do this by reading the React props off the DOM.
    const w = makeWindow();
    render(<EcosystemWindow window={w} isFocused={true} />);
    const iframe = screen.getByTestId(
      'atrium-window-karafiel-iframe',
    ) as HTMLIFrameElement;
    // Pull the onError handler React attached and call it directly.
    // This is implementation-detail-y but it's how we exercise the
    // failure path deterministically without relying on jsdom firing
    // resource error events.
    const propsKey = Object.keys(iframe).find((k) =>
      k.startsWith('__reactProps$'),
    );
    expect(propsKey).toBeTruthy();
    const props = (iframe as unknown as Record<string, unknown>)[
      propsKey as string
    ] as { onError?: (e: unknown) => void };
    expect(typeof props.onError).toBe('function');
    await act(async () => {
      props.onError!({} as unknown);
    });
    expect(
      screen.getByTestId('atrium-window-karafiel-fallback'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('atrium-window-karafiel-open-tab'),
    ).toHaveAttribute('href', 'https://app.karafiel.mx');
    expect(
      screen.getByTestId('atrium-window-karafiel-why'),
    ).toBeInTheDocument();
    // Window chrome (title bar) remains.
    expect(
      screen.getByTestId('atrium-window-karafiel-titlebar'),
    ).toBeInTheDocument();
  });
});
