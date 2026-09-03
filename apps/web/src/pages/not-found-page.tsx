import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <section className="mx-auto max-w-xl py-20 text-center">
      <p className="text-sm font-medium text-primary">Ошибка 404</p>
      <h1 className="mt-3 text-3xl font-semibold">Страница не найдена</h1>
      <p className="mt-4 mb-8 text-muted-foreground">
        Возможно, адрес изменился или страница ещё не реализована.
      </p>
      <Button asChild variant="secondary">
        <Link to="/">На главную</Link>
      </Button>
    </section>
  );
}
