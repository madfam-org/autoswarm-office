// CONVENTION: snake_case fields. These types mirror the wire shape of
// the Python API exactly — the runtime client receives them as-is from
// JSON and consumes the same field names. Do NOT camelCase here; keep
// the field names byte-identical to the Janua guest-token endpoint
// (`POST /api/v1/auth/guest`) and the GuestInvite model.

/** Guest access types shared between frontend and backend. */

export interface GuestTokenRequest {
  display_name?: string;
  org_id?: string;
  invite_token?: string;
  ttl_hours?: number;
}

export interface GuestTokenResponse {
  access_token: string;
  expires_at: string;
  guest_id: string;
  display_name: string;
  org_id: string;
}

export interface GuestInviteValidation {
  valid: boolean;
  org_name?: string;
  room_id?: string;
  expires_at?: string;
}
