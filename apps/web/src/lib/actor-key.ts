/*
  Ключ отправителя оценок. API хранит обратную связь с уникальностью
  (finding_id, actor_key), поэтому общий ключ на всех означал бы, что оценка
  второго человека молча затирает оценку первого, а в выгрузке нельзя понять,
  чья она. Для сбора разметки у заказчика это неприемлемо: именно она и есть
  показатель пользы, ради которого всё собирается.

  Ключ неперсональный — случайный идентификатор, никаких имён и почт.
  Он лишь разделяет оценщиков между собой.

  Держим в localStorage, а не в sessionStorage: разметка одного человека
  должна оставаться его разметкой между заходами, иначе каждое открытие
  вкладки выглядело бы как новый оценщик и статистика распалась бы.
  Учётные данные, наоборот, живут в sessionStorage — там короткая жизнь
  как раз желательна.
*/
const STORAGE_KEY = "docreview.actor-key";

/** Случайный идентификатор без crypto.randomUUID.

    На боевом адресе randomUUID работает (проверено по журналу API), но он
    объявлен доступным только в защищённом контексте, а контур раздаётся по
    http — полагаться на это в другом браузере нельзя. Нужна не
    криптостойкость, а различимость оценщиков, поэтому запасной путь годится. */
function fallbackId(): string {
  const random = () => Math.random().toString(36).slice(2, 10);
  return `${Date.now().toString(36)}-${random()}${random()}`;
}

function generate(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return `web-${crypto.randomUUID()}`;
    }
  } catch {
    /* недоступно — уходим на запасной путь */
  }
  return `web-${fallbackId()}`;
}

/** Ключ этого браузера: сохранённый либо только что созданный.

    Если хранилище недоступно (приватный режим, запрет на сайт-данные),
    ключ живёт в памяти до перезагрузки страницы: оценки в пределах одного
    захода всё равно останутся связными. */
let inMemory: string | null = null;

export function currentActorKey(): string {
  if (inMemory) return inMemory;

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      inMemory = stored;
      return stored;
    }
  } catch {
    /* читать нечем — создадим ключ и оставим его в памяти */
  }

  const created = generate();
  inMemory = created;
  try {
    window.localStorage.setItem(STORAGE_KEY, created);
  } catch {
    /* переживёт до перезагрузки страницы */
  }
  return created;
}
