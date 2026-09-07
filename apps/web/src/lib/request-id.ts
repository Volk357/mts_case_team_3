/*
  Идентификатор запроса для заголовка Idempotency-Key.

  Почему не `crypto.randomUUID()` напрямую. Он объявлен доступным только в
  защищённом контексте, а контур раздаётся по http — и там его нет вовсе:
  `typeof crypto.randomUUID === "undefined"`, вызов падает с TypeError.
  Падал он ДО отправки запроса, поэтому на сервере не оставалось следа, а
  человек видел «Не удалось загрузить документ» и не мог запустить проверку
  из интерфейса совсем.

  Почему этого не поймали тесты: Playwright и dev-сервер работают на
  localhost, а localhost считается защищённым контекстом — там randomUUID
  есть. Ошибка воспроизводится только по сетевому адресу без TLS.

  `crypto.getRandomValues` ограничения защищённого контекста НЕ касаются,
  поэтому основной путь — он. Math.random остаётся последним рубежом:
  ключу нужна не криптостойкость, а различимость повторных отправок.
*/

function fromGetRandomValues(): string | null {
  try {
    if (typeof crypto === "undefined" || typeof crypto.getRandomValues !== "function") {
      return null;
    }
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    // Приводим к виду UUID v4: так значение остаётся привычным в журналах.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return [
      hex.slice(0, 8),
      hex.slice(8, 12),
      hex.slice(12, 16),
      hex.slice(16, 20),
      hex.slice(20),
    ].join("-");
  } catch {
    return null;
  }
}

function fromMathRandom(): string {
  const chunk = () => Math.random().toString(36).slice(2, 10);
  return `${Date.now().toString(36)}-${chunk()}${chunk()}`;
}

/** Уникальный ключ запроса. Работает и без защищённого контекста. */
export function newRequestId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    /* недоступно — уходим на запасной путь */
  }
  return fromGetRandomValues() ?? fromMathRandom();
}
