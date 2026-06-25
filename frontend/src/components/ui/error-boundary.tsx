import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Translations } from "@/core/i18n/locales";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * React error boundary that catches render errors in its subtree
 * and displays a friendly error card instead of a blank screen.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("[ErrorBoundary] Uncaught error:", error, errorInfo);
    if (this.isChunkLoadError(error)) {
      const key = "octopus:chunk-reload-once";
      if (window.sessionStorage.getItem(key) !== "1") {
        window.sessionStorage.setItem(key, "1");
        window.location.reload();
      }
    }
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  // Chunk-load failures (deploy rolled forward, CDN blip, offline) surface as
  // a render error with a distinctive message — offer a hard reload instead
  // of the generic retry, which just re-renders the same broken subtree.
  private isChunkLoadError(err: Error | null): boolean {
    if (!err) return false;
    const msg = err.message || "";
    return (
      err.name === "ChunkLoadError" ||
      /Loading chunk .* failed/i.test(msg) ||
      /Failed to fetch dynamically imported module/i.test(msg) ||
      /Importing a module script failed/i.test(msg)
    );
  }

  handleReload = (): void => {
    window.sessionStorage.removeItem("octopus:chunk-reload-once");
    window.location.reload();
  };

  private renderErrorCard(t: Translations["errorBoundary"]): ReactNode {
    const chunkFailed = this.isChunkLoadError(this.state.error);
    return (
      <div className="flex items-center justify-center p-8">
        <Card className="max-w-lg border-border/70 bg-background/92 shadow-sm">
          <CardHeader>
            <CardTitle className="text-base text-foreground">
              {chunkFailed ? t.chunkTitle : t.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {chunkFailed
                ? t.chunkDescription
                : this.state.error?.message || t.unexpectedDescription}
            </p>
          </CardContent>
          <CardFooter className="gap-3">
            {chunkFailed ? (
              <Button variant="default" size="sm" onClick={this.handleReload}>
                {t.refreshPage}
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={this.handleReset}>
                {t.retry}
              </Button>
            )}
          </CardFooter>
        </Card>
      </div>
    );
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <I18nContext.Consumer>
          {(context) =>
            this.renderErrorCard((context?.t ?? enUS).errorBoundary)
          }
        </I18nContext.Consumer>
      );
    }

    return this.props.children;
  }
}

/**
 * HOC that wraps a component with an ErrorBoundary.
 * Useful for isolating individual route pages or panels
 * so one crash does not take down the entire workspace.
 *
 * @example
 * const SafePage = withErrorBoundary(MyPage, {
 *   fallback: <PanelErrorFallback />,
 * });
 */
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  options?: Omit<ErrorBoundaryProps, "children">,
) {
  function WithErrorBoundaryWrapper(props: P) {
    return (
      <ErrorBoundary {...options}>
        <WrappedComponent {...props} />
      </ErrorBoundary>
    );
  }
  WithErrorBoundaryWrapper.displayName = `withErrorBoundary(${
    WrappedComponent.displayName || WrappedComponent.name || "Component"
  })`;
  return WithErrorBoundaryWrapper;
}
