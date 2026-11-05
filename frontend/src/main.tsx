import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthProvider, useAuth } from "./auth";
import { Shell } from "./components/Shell";
import { Spinner } from "./components/ui";
import "./index.css";
import { Activity } from "./pages/Activity";
import { CloneVoice } from "./pages/CloneVoice";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Projects } from "./pages/Projects";
import { Studio } from "./pages/Studio";
import { VoiceLibrary } from "./pages/VoiceLibrary";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="min-h-dvh grid place-items-center">
        <Spinner />
      </div>
    );
  return user ? children : <Navigate to="/login" replace />;
}

function App() {
  const { user } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="voices" element={<VoiceLibrary />} />
        <Route path="voices/new" element={<CloneVoice />} />
        <Route path="projects" element={<Projects />} />
        <Route path="studio/:projectId" element={<Studio />} />
        <Route path="activity" element={<Activity />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
