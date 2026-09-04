import { Activity, FileCheck2, LogOut } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

import { clearCredentials, setToken } from "@/auth/session";

export function AppLayout() {
  const signOut = () => {
    clearCredentials();
    setToken(null);
    window.location.assign("/");
  };

  return (
    <div className="min-h-dvh">
      {/* Шапка липкая: список замечаний длинный, выход и возврат на главную
          не должны требовать прокрутки вверх на телефоне. */}
      <header className="sticky top-0 z-20 border-b border-border bg-navy pt-[env(safe-area-inset-top)]">
        <div className="px-gutter mx-auto flex h-14 max-w-3xl items-center justify-between gap-4 sm:h-16">
          <Link
            className="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight text-white"
            to="/"
          >
            <FileCheck2 aria-hidden="true" className="size-5 text-accent" />
            DocReview
          </Link>
          <nav className="flex items-center gap-1 sm:gap-2">
            <Link
              className="inline-flex h-11 items-center gap-2 rounded-(--radius-sm) px-2.5 text-sm font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white sm:px-3"
              to="/debug/health"
            >
              <Activity aria-hidden="true" className="size-4" />
              <span className="sr-only sm:not-sr-only">Состояние системы</span>
            </Link>
            <button
              className="inline-flex h-11 items-center gap-2 rounded-(--radius-sm) px-2.5 text-sm font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white sm:px-3"
              onClick={signOut}
              type="button"
            >
              <LogOut aria-hidden="true" className="size-4" />
              <span className="sr-only sm:not-sr-only">Выйти</span>
            </button>
          </nav>
        </div>
      </header>
      <main className="px-gutter mx-auto max-w-3xl pt-8 pb-[max(3rem,env(safe-area-inset-bottom))] sm:pt-12 sm:pb-16">
        <Outlet />
      </main>
    </div>
  );
}
