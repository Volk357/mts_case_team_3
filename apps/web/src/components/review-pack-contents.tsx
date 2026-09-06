import { Check, Minus } from "lucide-react";
import { useEffect, useState } from "react";

import { getReviewPacks, type ReviewPack } from "@/api/review-packs";

/**
 * Состав активного Review Pack — чем проверка перенастраивается под другую
 * организацию.
 *
 * Зачем этот блок нужен. Главное продуктовое утверждение — «под другую
 * компанию настраивается конфигурацией, а не кодом» — до сих пор жило только
 * в презентации, и проверить его никто не мог. Здесь показан фактический
 * состав пакета, который применяется прямо сейчас: имена файлов, что каждый
 * задаёт, и лежит ли он в пакете на самом деле.
 *
 * Отсутствующий файл показывается отсутствующим, а не прячется: если в пакете
 * нет политики приёмки, человек должен знать, что работают умолчания ядра,
 * а не думать, что политика задана.
 */
export function ReviewPackContents() {
  const [pack, setPack] = useState<ReviewPack | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getReviewPacks(controller.signal)
      .then((catalog) => setPack(catalog.items[0] ?? null))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setFailed(true);
        }
      });
    return () => controller.abort();
  }, []);

  // Блок пояснительный: пока каталог не ответил или ответил ошибкой, экран
  // должен выглядеть целым, а не показывать пустую рамку или сообщение об
  // ошибке там, где человек ничего не запрашивал.
  if (failed || !pack || pack.contents.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="pack-contents-title">
      <div className="rounded-(--radius-card) border border-border bg-card p-5 sm:p-6">
        <h2 className="font-semibold" id="pack-contents-title">
          Что меняется под другую организацию
        </h2>
        <p className="mt-1.5 text-sm leading-6 text-text-secondary">
          Правила проверки лежат в версионируемом наборе файлов, а не в коде. Сейчас применяется{" "}
          <span className="font-medium text-text">{pack.display_name}</span>, версия{" "}
          <span className="font-mono text-[0.9em]">{pack.version}</span>.
        </p>

        <ul className="mt-5 grid gap-px overflow-hidden rounded-(--radius-card) border border-border bg-border">
          {pack.contents.map((part) => (
            <li className="flex gap-3 bg-card p-4 sm:p-5" key={part.key}>
              <span
                aria-hidden="true"
                className={
                  part.present
                    ? "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent"
                    : "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-border text-text-secondary"
                }
              >
                {part.present ? <Check className="size-3" /> : <Minus className="size-3" />}
              </span>
              <div className="min-w-0">
                <p className="font-mono text-sm font-medium break-words">{part.filename}</p>
                <p className="mt-1 text-sm leading-6 text-text-secondary">{part.description}</p>
                {!part.present && (
                  <p className="mt-1 text-sm leading-6 text-text-secondary">
                    В этом наборе не задан — применяются значения по умолчанию.
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>

        <p className="mt-4 text-sm leading-6 text-text-secondary">
          Чтобы применить инструмент в другой организации, заменяются эти файлы. Код приложения
          и модель при этом не меняются.
        </p>
      </div>
    </section>
  );
}
