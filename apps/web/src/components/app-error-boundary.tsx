import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  failed: boolean;
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled frontend render error", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <main className="mx-auto grid min-h-screen max-w-xl place-items-center px-4 py-12">
        <Card className="space-y-5 p-6 text-center" role="alert">
          <div>
            <p className="text-sm font-semibold text-danger">Ошибка интерфейса</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">
              Не удалось отобразить страницу
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Обновите страницу. Если ошибка повторится, сообщите команде поддержки время
              возникновения ошибки.
            </p>
          </div>
          <Button asChild>
            <a href="/">Вернуться на главную</a>
          </Button>
        </Card>
      </main>
    );
  }
}
