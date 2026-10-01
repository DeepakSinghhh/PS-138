import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** "page" replaces the whole page body; "inline" stands in for one chart or section */
  variant?: "page" | "inline";
  /** a change in this value clears the error (e.g. the route, or the chart's data) */
  resetKey?: unknown;
}
interface State { error: Error | null }

/** Contains a render error to the section that threw, instead of blanking the whole app. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Q-GreenFleet: a section failed to render", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const retry = () => this.setState({ error: null });
    if (this.props.variant === "inline") {
      return (
        <div className="empty" role="alert" style={{ minHeight: 140 }}>
          <div>
            This chart could not be drawn ({error.message || "unknown error"}).
            <div style={{ marginTop: 10 }}><button className="btn" onClick={retry}>Try again</button></div>
          </div>
        </div>
      );
    }
    return (
      <div className="card" role="alert">
        <h3>Something went wrong on this page</h3>
        <p className="secondary">{error.message || "Unknown error"}. The rest of the app still works; try again or open another page.</p>
        <div className="btn-row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={retry}>Try again</button>
          <button className="btn" onClick={() => window.location.reload()}>Reload the app</button>
        </div>
      </div>
    );
  }
}
