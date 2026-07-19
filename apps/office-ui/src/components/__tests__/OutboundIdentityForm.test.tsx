/**
 * Tests for OutboundIdentityForm — the tenant-side outbound identity
 * configuration UI (Phase 2 of the v2.2.x email lockdown remediation).
 *
 * Mocks ``apiFetch`` directly to avoid wiring a full http stack into
 * jsdom. Verifies the form's three guarantees:
 * - Renders pre-populated with the server's resolved identity.
 * - Surfaces an inline email-format error on blur.
 * - PUTs the right shape on submit and shows a success toast.
 */
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ToastProvider } from '../Toast';
import { OutboundIdentityForm } from '../OutboundIdentityForm';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  // ToastProvider transitively imports useDemoMode → isDemo → getSessionToken.
  // Stub the rest so the mock module satisfies every consumer.
  isDemo: () => false,
  isAdmin: () => false,
  isGuest: () => false,
  getSessionToken: () => null,
  getSessionUser: () => null,
}));

// Helper to mint a fetch-style Response without depending on the
// runtime fetch (jsdom may or may not ship a global Response).
function jsonResponse(body: unknown, init: { status?: number } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderWithToast() {
  return render(
    <ToastProvider>
      <OutboundIdentityForm />
    </ToastProvider>,
  );
}

describe('OutboundIdentityForm', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('renders inputs pre-populated with server-resolved identity', async () => {
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({
        user_email: 'team@tenant.example',
        user_name: 'Tenant Team',
        org_name: 'Tenant S.A.',
        agent_slug: 'sales',
      }),
    );

    renderWithToast();

    // useEffect that seeds the form fires AFTER the initial render
    // returns the input — wait for the value to actually populate.
    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(emailInput.value).toBe('team@tenant.example'));

    const nameInput = screen.getByLabelText(/Display name/i) as HTMLInputElement;
    const slugSelect = screen.getByLabelText(/Pinned agent slug/i) as HTMLSelectElement;
    expect(nameInput.value).toBe('Tenant Team');
    expect(slugSelect.value).toBe('sales');
  });

  it('renders empty inputs when the server returns null fields', async () => {
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({
        user_email: null,
        user_name: null,
        org_name: null,
        agent_slug: null,
      }),
    );

    renderWithToast();

    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;
    expect(emailInput.value).toBe('');
    expect((screen.getByLabelText(/Display name/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/Pinned agent slug/i) as HTMLSelectElement).value).toBe('');
  });

  it('surfaces inline email validation error on blur', async () => {
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({ user_email: null, user_name: null, org_name: null, agent_slug: null }),
    );

    renderWithToast();

    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;

    // Root cause of this test's long-running flake: the identity GET resolves
    // on a microtask and its load effect calls
    // setEmailInput(identity.user_email ?? '') — with the mock's
    // user_email:null that RESETS the field to ''. If it lands after the test
    // types, it wipes the value and blur then validates an empty string, so no
    // error is set. (Earlier render-race / stale-closure fixes missed this
    // GET→reset interference.) Retrying the whole type→blur→assert in one
    // waitFor makes it deterministic: whichever order the microtask lands, the
    // sequence re-runs until the error sticks.
    await waitFor(() => {
      fireEvent.change(emailInput, { target: { value: 'not-an-email' } });
      fireEvent.blur(emailInput);
      const err = screen.getByRole('alert');
      expect(err.textContent).toMatch(/valid email address/i);
      expect(emailInput.getAttribute('aria-invalid')).toBe('true');
    });
  });

  it('submits PUT with the right payload and shows a success toast', async () => {
    // Initial GET
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({
        user_email: 'old@tenant.example',
        user_name: 'Old Name',
        org_name: null,
        agent_slug: 'sales',
      }),
    );
    // PUT response — server echoes back the new resolved identity.
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({
        user_email: 'ceo@tenant.example',
        user_name: 'Tenant CEO',
        org_name: null,
        agent_slug: 'growth',
      }),
    );

    renderWithToast();

    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;
    const nameInput = screen.getByLabelText(/Display name/i) as HTMLInputElement;
    const slugSelect = screen.getByLabelText(/Pinned agent slug/i) as HTMLSelectElement;
    await waitFor(() => {
      expect(emailInput.value).toBe('old@tenant.example');
      expect(nameInput.value).toBe('Old Name');
      expect(slugSelect.value).toBe('sales');
    });

    await act(async () => {
      fireEvent.change(emailInput, { target: { value: 'ceo@tenant.example' } });
      fireEvent.change(nameInput, { target: { value: 'Tenant CEO' } });
      fireEvent.change(slugSelect, { target: { value: 'growth' } });
    });
    await waitFor(() => {
      expect(emailInput.value).toBe('ceo@tenant.example');
      expect(nameInput.value).toBe('Tenant CEO');
      expect(slugSelect.value).toBe('growth');
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    });

    // PUT was the second call (after the initial GET).
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));
    const putCall = apiFetchMock.mock.calls[1];
    expect(putCall[0]).toBe('/api/v1/onboarding/tenant-identity');
    expect(putCall[1]?.method).toBe('PUT');
    expect(JSON.parse(putCall[1]?.body as string)).toEqual({
      outbound_user_email: 'ceo@tenant.example',
      outbound_user_name: 'Tenant CEO',
      outbound_agent_slug: 'growth',
    });

    // Success toast surfaces in the live region.
    expect(await screen.findByText('Outbound identity updated')).toBeInTheDocument();
  });

  it('clears columns by sending null when fields are emptied', async () => {
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({
        user_email: 'old@tenant.example',
        user_name: 'Old Name',
        org_name: null,
        agent_slug: 'sales',
      }),
    );
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({ user_email: null, user_name: null, org_name: null, agent_slug: null }),
    );

    renderWithToast();

    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;
    // Wait for the GET to actually hydrate the input. Without this
    // the useEffect that seeds the form may run AFTER our fireEvent
    // and clobber our changes back to the server values.
    await waitFor(() => expect(emailInput.value).toBe('old@tenant.example'));

    const nameInput = screen.getByLabelText(/Display name/i) as HTMLInputElement;
    const slugSelect = screen.getByLabelText(/Pinned agent slug/i) as HTMLSelectElement;

    fireEvent.change(emailInput, { target: { value: '' } });
    fireEvent.change(nameInput, { target: { value: '' } });
    fireEvent.change(slugSelect, { target: { value: '' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    });

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));
    const putBody = JSON.parse(apiFetchMock.mock.calls[1][1]?.body as string);
    expect(putBody).toEqual({
      outbound_user_email: null,
      outbound_user_name: null,
      outbound_agent_slug: null,
    });
  });

  it('shows error toast when API returns a validation failure', async () => {
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse({ user_email: null, user_name: null, org_name: null, agent_slug: null }),
    );
    // Simulate the backend rejecting the email format (FastAPI 422 with a
    // structured detail). The form's client-side validator should
    // normally catch this first, but the toast path is exercised when
    // the regex differs (e.g. backend tightened, frontend not yet).
    apiFetchMock.mockResolvedValueOnce(
      jsonResponse(
        { detail: [{ loc: ['body', 'outbound_user_email'], msg: 'invalid' }] },
        { status: 422 },
      ),
    );

    renderWithToast();

    const emailInput = (await screen.findByLabelText(
      /Outbound mailbox/i,
    )) as HTMLInputElement;
    // Bypass the client-side regex by using a value that passes it but
    // we'll mock the server rejecting anyway.
    fireEvent.change(emailInput, { target: { value: 'looks@valid.email' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    });

    // The toast container's aria-live region picks up the error message.
    await waitFor(() => {
      const alerts = screen.getAllByRole('alert');
      const found = alerts.some((el) => /invalid|outbound_user_email/.test(el.textContent ?? ''));
      expect(found).toBe(true);
    });
  });
});
