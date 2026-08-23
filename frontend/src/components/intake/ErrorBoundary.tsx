/**
 * Catches render errors so they surface instead of blanking the page.
 *
 * Without this, one thrown error inside any route unmounts the whole tree and
 * React leaves an empty body behind. The symptom is "nothing loads", which
 * points at the network — and the network is usually fine, so the real cause
 * goes unlooked-at while the API gets blamed.
 *
 * A class component because there is still no hook equivalent:
 * componentDidCatch has no functional counterpart.
 */

import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    // Kept as console.error rather than swallowed: the stack is the only thing
    // that identifies which component threw.
    console.error("Render error:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <main className="wrap">
        <div className="nb-card">
          <h1>Something broke on this screen</h1>
          <p className="hint">
            The page failed to render. This is a bug in the interface, not a
            problem with your data — nothing has been lost.
          </p>
          <pre className="my-3 overflow-x-auto rounded-xl border border-line bg-paper p-3 text-sm">
            {error.message}
          </pre>
          <div className="flex gap-2.5">
            <button
              className="nb-btn nb-btn-primary"
              onClick={() => this.setState({ error: null })}
            >
              Try again
            </button>
            <button
              className="nb-btn"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      </main>
    );
  }
}
