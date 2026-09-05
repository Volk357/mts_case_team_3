/*
  Вход поверх basic-auth. Учётные данные проверяет nginx на /api/ —
  своего механизма аутентификации у приложения пока нет, и выдумывать его
  здесь было бы хуже, чем честно опереться на существующий.

  Что это даёт: вместо серого окна браузера человек видит нормальную форму,
  а неверный пароль отличим от недоступного сервера. Что не даёт: это те же
  basic-credentials, роли и учётные записи здесь не появляются.

  Держим в sessionStorage: вкладку закрыли — доступ закончился. localStorage
  для чужого компьютера был бы хуже.
*/
const STORAGE_KEY = "docreview.credentials";

export function readCredentials(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // приватный режим или заблокированное хранилище
  }
}

export function saveCredentials(login: string, password: string): string {
  // btoa не переваривает кириллицу — кодируем через UTF-8, как требует RFC 7617
  const bytes = new TextEncoder().encode(`${login}:${password}`);
  const token = btoa(String.fromCharCode(...bytes));
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* без хранилища вход проживёт до перезагрузки страницы */
  }
  return token;
}

export function clearCredentials(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* нечего чистить */
  }
}

let inMemory: string | null = null;

/** Токен для заголовка Authorization: сначала память, затем хранилище. */
export function currentToken(): string | null {
  return inMemory ?? readCredentials();
}

export function setToken(token: string | null): void {
  inMemory = token;
}
