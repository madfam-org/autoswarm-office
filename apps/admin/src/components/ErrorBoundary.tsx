'use client';

import { Component, type ReactNode, type ErrorInfo } from 'react';
import { logger } from '@/lib/logger';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logger.error('[ErrorBoundary]', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen w-full flex-col items-center justify-center gap-4 bg-slate-900 p-8">
          <h1 className="font-mono text-lg font-bold uppercase tracking-widest text-red-400">
            Something went wrong
          </h1>
          <p className="max-w-md text-center font-mono text-sm text-slate-400">
            {this.state.error?.message ?? 'An unexpected error occurred.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="rounded bg-indigo-600 px-6 py-2 font-mono text-sm text-white hover:bg-indigo-500"
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
