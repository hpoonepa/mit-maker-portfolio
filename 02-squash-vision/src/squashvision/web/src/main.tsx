import "@fontsource/inter-tight/latin-400.css";
import "@fontsource/inter-tight/latin-500.css";
import "@fontsource/inter-tight/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/library.css";
import "./styles/workflow.css";
import "./styles/analysis.css";
import "./styles/reports.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Component, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { appRoutes } from "./router";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

class ApplicationErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("The local interface stopped safely", error, info.componentStack);
  }

  render() {
    if (this.state.error !== null) {
      return (
        <main className="fatal-state" role="alert">
          <p className="eyebrow">Local interface error</p>
          <h1>The match workspace stopped safely</h1>
          <p>Reload the interface. Videos and completed analysis remain on this device.</p>
          <button type="button" className="button-primary" onClick={() => window.location.reload()}>Reload interface</button>
        </main>
      );
    }
    return this.props.children;
  }
}

export function App() {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 5_000 },
      mutations: { retry: false },
    },
  }));
  const [router] = useState(() => createBrowserRouter(appRoutes));

  return (
    <ApplicationErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ApplicationErrorBoundary>
  );
}

const rootElement = document.getElementById("root");
if (rootElement !== null) createRoot(rootElement).render(<App />);
