import { FileCheck2, LogOut } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

import { clearCredentials, setToken } from "@/auth/session";

export function AppLayout() {
  const signOut = () => {
    clearCredentials();
    setToken(null);
    window.location.assign("/");
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-navy">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Link className="flex items-center gap-2.5 font-semibold tracking-tight text-white" to="/">
            <FileCheck2 aria-hidden="true" className="size-5 text-accent" />
            DocReview
          </Link>
          <div className="flex items-center gap-6">
            <Link
              className="text-sm font-medium text-white/75 transition-colors hover:text-white"
              to="/debug/health"
            >
              Состояние системы
            </Link>
            <button
              className="inline-flex items-center gap-2 text-sm font-medium text-white/75 transition-colors hover:text-white"
              onClick={signOut}
              type="button"
            >
              <LogOut aria-hidden="true" className="size-4" />
              Выйти
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-12">
        <Outlet />
      </main>
    </div>
  );
}
