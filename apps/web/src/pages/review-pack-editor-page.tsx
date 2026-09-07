import { yaml } from "@codemirror/lang-yaml";
import CodeMirror from "@uiw/react-codemirror";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import {
  createReviewPackVersion,
  getReviewPackSource,
  getReviewPacks,
  type ReviewPack,
  type ReviewPackSource,
} from "@/api/review-packs";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/*
  Редактор правил проверки.

  Главное продуктовое утверждение — «под другую организацию перенастраивается
  конфигурацией, а не кодом». До сих пор конфигурацию можно было только
  посмотреть: менять её приходилось по ssh, и проверить утверждение
  пользователь не мог.

  Два решения, которые определяют весь экран.

  Первое: правка НЕ сохраняется поверх. Опубликованная версия неизменяема,
  потому что на неё ссылаются прошлые проверки, а её номер входит в результат
  анализа и сверяется приложением. Поэтому кнопка называется «Выпустить
  версию», а не «Сохранить», и номер версии человек вводит сам — он должен
  осознавать, что создаёт то, на что будут ссылаться.

  Второе: файл проверяет ЯДРО, а не браузер. Разбирать YAML здесь значило бы
  завести вторую проверку, которая разойдётся с первой, и показать «всё
  хорошо» там, где анализ откажет. Поэтому ошибка приходит от сервера
  дословно и показывается как есть.
*/

/** Подписи файлов: те же формулировки, что в блоке состава пакета. */
const FILE_LABELS: Record<string, { title: string; hint: string }> = {
  template: {
    title: "template.yaml",
    hint: "Структура документа: какие разделы обязательны и что в них проверяется",
  },
  defects: {
    title: "defects.yaml",
    hint: "Таксономия дефектов и конвенции компании — что считать ошибкой",
  },
  glossary: {
    title: "glossary.yaml",
    hint: "Термины, которые в компании не расшифровывают",
  },
  policy: {
    title: "policy.yaml",
    hint: "Политика приёмки: сколько замечаний показывать и что дороже — пропуск или шум",
  },
};

const FILE_ORDER = ["template", "defects", "glossary", "policy"];

/** Номер версии по умолчанию: свободный, а не просто следующий.

    Наивный инкремент последней части давал занятый номер: у профиля 0.2
    уже существует 0.3 — другой режим того же профиля. Человек нажимал
    «Выпустить» и получал конфликт на ровном месте.

    Поэтому предлагаем уточняющую версию (0.2 → 0.2.1) и проверяем её
    по каталогу. Номер остаётся полем ввода: последнее слово за человеком. */
function suggestVersion(current: string, taken: readonly string[]): string {
  const occupied = new Set(taken);
  for (let n = 1; n <= 50; n += 1) {
    const candidate = `${current}.${n}`;
    if (!occupied.has(candidate)) return candidate;
  }
  return `${current}.new`;
}

/** Выпуск версии меняет параметр адреса, а не маршрут, поэтому React оставил бы
    прежний экран со всем его состоянием: кнопка навсегда читалась бы
    «Проверяем и выпускаем». Ключ по packId делает переход на новую версию
    честным открытием новой страницы. Поймано на живом стенде. */
export function ReviewPackEditorPage() {
  const { packId = "" } = useParams();
  return <PackEditor key={packId} packId={packId} />;
}

function PackEditor({ packId }: { packId: string }) {
  const navigate = useNavigate();

  const [source, setSource] = useState<ReviewPackSource | null>(null);
  const [pack, setPack] = useState<ReviewPack | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [active, setActive] = useState<string>("policy");
  const [version, setVersion] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<{ code?: string; message: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getReviewPackSource(packId, controller.signal),
      getReviewPacks(controller.signal).catch(() => null),
    ])
      .then(([loaded, catalog]) => {
        setSource(loaded);
        setDrafts(loaded.files);
        setVersion(
          suggestVersion(loaded.version, (catalog?.items ?? []).map((item) => item.version)),
        );
        const keys = FILE_ORDER.filter((key) => key in loaded.files);
        setActive(keys.includes("policy") ? "policy" : (keys[0] ?? ""));
        setPack(catalog?.items.find((item) => item.review_pack_id === packId) ?? null);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLoadError(
          error instanceof ApiError && error.status === 404
            ? "Профиль проверки не найден."
            : "Не удалось загрузить правила профиля.",
        );
      });
    return () => controller.abort();
  }, [packId]);

  // Показываем только те файлы, которые ядро реально применяет: править
  // файл, который ядро проигнорирует, — обман.
  const keys = useMemo(
    () => FILE_ORDER.filter((key) => key in drafts),
    [drafts],
  );
  const changed = useMemo(
    () => (source ? keys.filter((key) => drafts[key] !== source.files[key]) : []),
    [drafts, keys, source],
  );

  const release = async () => {
    if (!source || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const created = await createReviewPackVersion(packId, version.trim(), drafts);
      // Новая версия — другой профиль в каталоге. Смена packId в адресе
      // перечитывает страницу сама, полная перезагрузка не нужна.
      void navigate(`/review-packs/${created.review_pack_id}/edit`);
    } catch (error: unknown) {
      const parsed = error instanceof ApiError ? { code: error.code, message: error.message } : {};
      setSaveError({
        code: parsed.code,
        message:
          parsed.message ??
          "Не удалось выпустить версию. Проверьте соединение и повторите.",
      });
      setSaving(false);
    }
  };

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <Card className="p-5 sm:p-6">
          <p className="text-sm leading-6 text-red">{loadError}</p>
          <Link className="mt-4 inline-flex text-sm text-accent" to="/">
            Вернуться к проверке документа
          </Link>
        </Card>
      </div>
    );
  }

  if (!source) {
    return (
      <div className="mx-auto flex w-full max-w-3xl items-center gap-2 text-sm text-text-secondary">
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
        Загружаем правила профиля
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Link className="inline-flex items-center gap-2 text-sm text-text-secondary" to="/">
        <ArrowLeft aria-hidden="true" className="size-4" />
        Проверить документ
      </Link>

      <h1 className="mt-4 text-2xl font-semibold">Правила профиля</h1>
      <p className="mt-1.5 text-sm leading-6 text-text-secondary">
        {pack?.display_name ?? source.display_name}, версия{" "}
        <span className="font-mono text-[0.9em]">{source.version}</span>. Правка не
        меняет эту версию: на неё ссылаются уже выполненные проверки. Изменения
        выпускаются новой версией, и профиль выбирается при запуске проверки.
      </p>

      <div aria-label="Файлы правил" className="mt-5 flex flex-wrap gap-2" role="tablist">
        {keys.map((key) => (
          <button
            aria-selected={key === active}
            className={
              key === active
                ? "rounded-(--radius-sm) border border-accent bg-accent/10 px-3 py-1.5 font-mono text-sm text-accent"
                : "rounded-(--radius-sm) border border-border px-3 py-1.5 font-mono text-sm text-text-secondary"
            }
            key={key}
            onClick={() => setActive(key)}
            role="tab"
            type="button"
          >
            {FILE_LABELS[key]?.title ?? key}
            {changed.includes(key) && <span aria-label="изменён"> ·</span>}
          </button>
        ))}
      </div>

      {active && (
        <>
          <p className="mt-3 text-sm leading-6 text-text-secondary">
            {FILE_LABELS[active]?.hint}
          </p>
          <div className="mt-3 overflow-hidden rounded-(--radius-card) border border-border">
            <CodeMirror
              aria-label={`Содержимое ${FILE_LABELS[active]?.title ?? active}`}
              extensions={[yaml()]}
              height="420px"
              onChange={(next) => setDrafts((current) => ({ ...current, [active]: next }))}
              value={drafts[active] ?? ""}
            />
          </div>
        </>
      )}

      <Card className="mt-5 p-5 sm:p-6">
        <h2 className="font-semibold">Выпустить новую версию</h2>
        <p className="mt-1.5 text-sm leading-6 text-text-secondary">
          {changed.length === 0
            ? "Пока ничего не изменено."
            : `Изменено файлов: ${changed.length}. Прежняя версия останется доступной.`}
        </p>

        <label className="mt-4 block text-sm font-medium" htmlFor="pack-version">
          Номер версии
        </label>
        <input
          className="mt-1.5 w-full max-w-56 rounded-(--radius-sm) border border-border bg-surface px-3 py-2 font-mono text-base"
          id="pack-version"
          onChange={(event) => setVersion(event.target.value)}
          value={version}
        />

        {saveError && (
          <div
            className="mt-4 rounded-(--radius-sm) bg-red-soft px-4 py-3"
            role="alert"
          >
            {/* Причина приходит от ядра дословно: без неё человек не поймёт,
                какую строку чинить, а придумывать своё объяснение значит
                гадать за проверяющий код. */}
            <p className="text-sm leading-6 text-red">{saveError.message}</p>
            {saveError.code && (
              <p className="mt-1 font-mono text-xs text-text-secondary">{saveError.code}</p>
            )}
          </div>
        )}

        <Button
          className="mt-4"
          disabled={saving || changed.length === 0 || !version.trim()}
          onClick={() => void release()}
          type="button"
        >
          {saving ? "Проверяем и выпускаем" : "Выпустить версию"}
        </Button>
        <p className="mt-3 text-sm leading-6 text-text-secondary">
          Перед публикацией правила проверяет ядро анализа — то же самое, что
          выполняет проверку документов. Пакет с ошибкой в каталог не попадёт.
        </p>
      </Card>
    </div>
  );
}
