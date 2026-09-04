import { FileCheck2 } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

export function AppLayout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-border/80 bg-card/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link className="flex items-center gap-3 font-semibold tracking-tight" to="/">
            <span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
              <FileCheck2 aria-hidden="true" className="size-5" />
            </span>
            DocReview
          </Link>
          <Link
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            to="/debug/health"
          >
            Состояние системы
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        <Outlet />
      </main>
    </div>
  );
}
