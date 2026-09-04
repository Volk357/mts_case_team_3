import { useState, type FormEvent } from "react";
import { LoaderCircle } from "lucide-react";

import { getHealth } from "@/api/health";
import { ApiError } from "@/api/client";
import { saveCredentials, setToken } from "@/auth/session";

interface SignInPageProps {
  onSignedIn: () => void;
}

/**
 * Вход проверяется тем же запросом, что и обычная работа: если /api/health
 * ответил, пароль верен. Отдельной ручки логина в приложении нет, и заводить
 * её здесь значило бы делать вид, что аутентификация уже есть.
 */
export function SignInPage({ onSignedIn }: SignInPageProps) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const token = saveCredentials(login.trim(), password);
    setToken(token);
    try {
      await getHealth();
      onSignedIn();
    } catch (cause) {
      setToken(null);
      if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
        setError("Логин или пароль не подошли. Проверьте раскладку и регистр.");
      } else {
        setError("Сервер не отвечает. Попробуйте ещё раз через минуту.");
      }
      setPending(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-navy px-16 py-14 lg:flex">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-40 -right-32 size-[34rem] rounded-full opacity-70 blur-3xl"
          style={{
            background:
              "radial-gradient(circle, rgb(13 148 136 / 34%) 0%, rgb(13 148 136 / 0%) 70%)",
          }}
        />
        <p className="relative text-sm font-medium tracking-wide text-white/55">
          Проверка аналитической документации
        </p>
        <div className="relative max-w-xl">
          <h1 className="text-4xl leading-[1.15] font-semibold tracking-tight text-white">
            Вопросы к документу видны до того, как он ушёл в разработку
          </h1>
          <p className="mt-6 text-lg leading-8 text-white/70">
            Инструмент читает готовое техническое задание и показывает места, где
            информации не хватает для однозначной реализации. Решение остаётся
            за аналитиком.
          </p>
        </div>
        <p className="relative max-w-lg text-sm leading-6 text-white/55">
          Каждое замечание опирается на дословную цитату из документа: если цитата
          не находится в тексте, замечание отбрасывается. На документ приходит
          не больше двадцати замечаний — столько аналитик успевает обдумать.
        </p>
      </section>

      <section className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-semibold tracking-tight">Вход</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Доступ выдаёт администратор контура.
          </p>

          <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label className="block text-sm font-medium" htmlFor="login">
                Логин
              </label>
              <input
                autoComplete="username"
                autoFocus
                className="h-11 w-full rounded-(--radius-sm) border border-border bg-card px-3.5 text-[0.9375rem] transition-colors outline-none placeholder:text-text-muted focus:border-accent"
                id="login"
                name="login"
                onChange={(event) => setLogin(event.target.value)}
                required
                value={login}
              />
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium" htmlFor="password">
                Пароль
              </label>
              <input
                autoComplete="current-password"
                className="h-11 w-full rounded-(--radius-sm) border border-border bg-card px-3.5 text-[0.9375rem] transition-colors outline-none focus:border-accent"
                id="password"
                name="password"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </div>

            {error ? (
              <p
                className="rounded-(--radius-sm) bg-red-soft px-3.5 py-3 text-sm leading-5 text-red"
                role="alert"
              >
                {error}
              </p>
            ) : null}

            <button
              className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-(--radius-sm) bg-accent text-[0.9375rem] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
              disabled={pending || !login.trim() || !password}
              type="submit"
            >
              {pending ? (
                <>
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                  Проверяем
                </>
              ) : (
                "Войти"
              )}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
