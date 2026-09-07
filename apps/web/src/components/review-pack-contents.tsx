import { Check, Minus, PencilLine } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
  const [packs, setPacks] = useState<ReviewPack[]>([]);
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(false);
  const pack = packs[index] ?? null;

  useEffect(() => {
    const controller = new AbortController();
    getReviewPacks(controller.signal)
      .then((catalog) => setPacks(catalog.items))
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
          Правила проверки лежат в версионируемом наборе файлов, а не в коде.
          {packs.length > 1 ? " Профиль выбирается при запуске проверки." : ""}
        </p>

        {/* Профилей несколько — показываем состав любого, а не только первого.
            Раньше блок жёстко брал items[0] и писал «сейчас применяется»,
            и после выбора второго профиля соседний блок противоречил выбору. */}
        {packs.length > 1 ? (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist">
            {packs.map((item, position) => (
              <button
                aria-selected={position === index}
                className={
                  position === index
                    ? "rounded-(--radius-sm) border border-accent bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent"
                    : "rounded-(--radius-sm) border border-border px-3 py-1.5 text-sm text-text-secondary"
                }
                key={item.review_pack_id}
                onClick={() => setIndex(position)}
                role="tab"
                type="button"
              >
                {/* Версия в подписи обязательна: имя у версий одного профиля
                    общее, и после выпуска новой версии из редактора в списке
                    оказывались две кнопки с одинаковым текстом. */}
                {item.display_name}{" "}
                <span className="font-mono text-[0.9em] opacity-70">{item.version}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-1.5 text-sm leading-6 text-text-secondary">
            Сейчас применяется <span className="font-medium text-text">{pack.display_name}</span>,
            версия <span className="font-mono text-[0.9em]">{pack.version}</span>.
          </p>
        )}

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

        {/* Вход в редактор. Пока файлы можно было только посмотреть,
            утверждение «настраивается конфигурацией» оставалось словами:
            поменять правила без ssh было нельзя. */}
        <Link
          className="mt-4 inline-flex items-center gap-2 text-sm text-accent"
          to={`/review-packs/${pack.review_pack_id}/edit`}
        >
          <PencilLine aria-hidden="true" className="size-4" />
          Изменить правила профиля
        </Link>
      </div>
    </section>
  );
}
