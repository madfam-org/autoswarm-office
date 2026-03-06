import { ReactNode } from 'react';

export interface JanuaProviderProps {
  children: ReactNode;
  issuerUrl?: string;
  clientId?: string;
  config?: { baseURL: string };
}

export function JanuaProvider(props: JanuaProviderProps): JSX.Element;

export interface JanuaUser {
  sub: string;
  email: string;
  roles: string[];
  org_id: string;
}

export function useJanua(): {
  user: JanuaUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signIn: () => void;
  signOut: () => void;
};

export function SignIn(props: { redirectUrl?: string }): JSX.Element;
