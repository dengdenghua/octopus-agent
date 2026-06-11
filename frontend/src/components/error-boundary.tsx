/* Implementation note. */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangleIcon, RefreshCwIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { I18nContext, type I18nContextType } from "@/core/i18n/context";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  static contextType = I18nContext;
  declare context: I18nContextType | null;
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const t = this.context?.t;

      return (
        <div className="flex min-h-[200px] items-center justify-center p-4">
          <Card className="w-full max-w-md">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <AlertTriangleIcon className="h-5 w-5 text-destructive" />
                <CardTitle className="text-base">{t?.errorBoundary.title ?? "Something went wrong"}</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t?.errorBoundary.description ?? "An error occurred while loading this component."}
              </p>
              {this.state.error && (
                <pre className="max-h-32 overflow-auto rounded bg-muted p-2 text-xs">
                  {this.state.error.message}
                </pre>
              )}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={this.handleReset}
                  className="flex-1"
                >
                  <RefreshCwIcon className="mr-1 h-4 w-4" />
                  {t?.errorBoundary.retry ?? "Retry"}
                </Button>
                <Button
                  size="sm"
                  onClick={() => window.location.reload()}
                  className="flex-1"
                >
                  {t?.errorBoundary.refreshPage ?? "Refresh page"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

/* Implementation note. */
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  options?: Omit<Props, "children">
) {
  return function WithErrorBoundaryWrapper(props: P) {
    return (
      <ErrorBoundary {...options}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
