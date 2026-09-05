import {
  AlertCircle,
  CheckCircle2,
  FileText,
  RefreshCw,
  UploadCloud,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { uploadDocument, type DocumentUploadResponse } from "@/api/documents";
import { getReviewPacks, type ReviewPack } from "@/api/review-packs";
import { createReview } from "@/api/reviews";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { appConfig } from "@/config";
import { cn } from "@/lib/utils";

/*
  DOCX, PDF и TXT. У форматов разная глубина разбора, и об этом честно
  предупреждает сам результат проверки: .docx даёт таблицы строками
  «ячейка | ячейка» и адреса гиперссылок, PDF разметки таблиц не хранит
  вовсе, а .txt — это уже извлечённый текст.
*/
const PDF_MEDIA_TYPE = "application/pdf";
const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const TXT_MEDIA_TYPE = "text/plain";
const ACCEPTED_FILES = `${PDF_MEDIA_TYPE},${DOCX_MEDIA_TYPE},${TXT_MEDIA_TYPE},.pdf,.docx,.txt`;

// Что браузер вправе прислать для каждого расширения. Текстовый файл
// помечают по-разному, вплоть до отсутствия типа, поэтому для .txt набор
// шире — иначе годный файл отбивался бы ещё до отправки.
const ACCEPTED_TYPES: Record<string, readonly string[]> = {
  ".pdf": [PDF_MEDIA_TYPE],
  ".docx": [DOCX_MEDIA_TYPE],
  ".txt": [TXT_MEDIA_TYPE, "text/markdown", "application/octet-stream", ""],
};

type UploadPhase = "idle" | "ready" | "uploading" | "success" | "starting" | "error";
type CatalogPhase = "loading" | "ready" | "empty" | "error";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function validateFile(file: File): string | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  const accepted = ACCEPTED_TYPES[extension];
  if (!accepted) return "Выберите документ в формате DOCX, PDF или TXT.";
  if (file.type && !accepted.includes(file.type)) {
    return "Расширение файла не соответствует его формату.";
  }
  if (file.size === 0) return "Файл пуст. Выберите документ с содержимым.";
  if (file.size > appConfig.maxUploadSizeBytes) {
    return `Файл больше допустимых ${formatBytes(appConfig.maxUploadSizeBytes)}.`;
  }
  return null;
}

function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return "Файл слишком большой для загрузки.";
    if (error.status === 415) return "Сервер принимает DOCX, PDF и TXT.";
    if (error.status === 422) return "Файл повреждён или его формат не подтверждён.";
    if (error.status === 0) return "Не удалось подключиться к серверу. Попробуйте ещё раз.";
  }
  return "Не удалось загрузить документ. Попробуйте ещё раз.";
}

export function FileDropzone() {
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<DocumentUploadResponse | null>(null);
  const [packs, setPacks] = useState<ReviewPack[]>([]);
  const [selectedPackId, setSelectedPackId] = useState<string | null>(null);
  const [catalogPhase, setCatalogPhase] = useState<CatalogPhase>("loading");
  const [catalogReload, setCatalogReload] = useState(0);
  const navigate = useNavigate();
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    void getReviewPacks(controller.signal)
      .then((catalog) => {
        setPacks(catalog.items);
        setSelectedPackId((current) =>
          catalog.items.some((pack) => pack.review_pack_id === current)
            ? current
            : (catalog.items[0]?.review_pack_id ?? null),
        );
        setCatalogPhase(catalog.items.length > 0 ? "ready" : "empty");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setPacks([]);
        setSelectedPackId(null);
        setCatalogPhase("error");
      });
    return () => controller.abort();
  }, [catalogReload]);

  const chooseFile = (nextFile: File | undefined) => {
    if (!nextFile) return;
    const validationError = validateFile(nextFile);
    setReceipt(null);
    setProgress(0);
    if (validationError) {
      setFile(null);
      setPhase("error");
      setMessage(validationError);
      return;
    }
    setFile(nextFile);
    setPhase("ready");
    setMessage(null);
  };

  const openPicker = () => {
    if (phase === "uploading" || phase === "starting") return;
    if (inputRef.current) inputRef.current.value = "";
    inputRef.current?.click();
  };

  const startUpload = async () => {
    if (!file || phase === "uploading") return;
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase("uploading");
    setMessage(null);
    setProgress(0);
    try {
      const result = await uploadDocument(file, setProgress, controller.signal);
      setReceipt(result);
      setPhase("success");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setPhase("error");
      setMessage(uploadErrorMessage(error));
    } finally {
      abortRef.current = null;
    }
  };

  const startReview = async () => {
    if (!receipt || !selectedPackId || phase === "starting") return;
    setPhase("starting");
    setMessage(null);
    try {
      const review = await createReview(
        receipt.document_id,
        selectedPackId,
        crypto.randomUUID(),
      );
      void navigate(`/reviews/${review.review_id}`);
    } catch (error) {
      setPhase("error");
      setMessage(uploadErrorMessage(error));
    }
  };

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (phase !== "uploading") chooseFile(event.dataTransfer.files[0]);
  };

  return (
    <Card className="overflow-hidden" id="upload">
      <div className="border-b border-border px-5 py-5 sm:px-8">
        <h2 className="text-lg font-semibold sm:text-xl">Загрузите документ</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          DOCX, PDF или TXT до {formatBytes(appConfig.maxUploadSizeBytes)}
        </p>
      </div>
      <div className="p-5 sm:p-8">
        <section aria-labelledby="review-pack-heading" className="mb-7">
          <div className="mb-3">
            <h3 className="font-semibold" id="review-pack-heading">
              Профиль проверки
            </h3>
            <p className="mt-1 text-sm leading-6 text-text-secondary">
              Профиль определяет правила и тип документа, по которым будет выполнена проверка.
            </p>
          </div>

          {catalogPhase === "loading" ? (
            <p aria-live="polite" className="text-sm text-text-muted">
              Загружаем доступные профили…
            </p>
          ) : null}

          {catalogPhase === "empty" ? (
            <p className="rounded-(--radius-sm) bg-amber-soft px-4 py-3 text-sm leading-6 text-amber">
              В контуре не настроен ни один доступный профиль проверки.
            </p>
          ) : null}

          {catalogPhase === "error" ? (
            <div className="flex flex-wrap items-center gap-3 rounded-(--radius-sm) bg-red-soft px-4 py-3 text-sm text-red">
              <span>Не удалось загрузить профили проверки.</span>
              <button
                className="font-medium underline underline-offset-4"
                onClick={() => {
                  setCatalogPhase("loading");
                  setCatalogReload((value) => value + 1);
                }}
                type="button"
              >
                Повторить
              </button>
            </div>
          ) : null}

          {catalogPhase === "ready" ? (
            <fieldset className="grid gap-3 sm:grid-cols-2" disabled={phase === "starting"}>
              <legend className="sr-only">Выберите профиль проверки</legend>
              {packs.map((pack) => {
                const selected = selectedPackId === pack.review_pack_id;
                return (
                  <label
                    className={cn(
                      "cursor-pointer rounded-(--radius-sm) border p-4 transition-colors",
                      selected
                        ? "border-primary bg-primary/5"
                        : "border-border bg-card hover:border-border-hover",
                    )}
                    key={pack.review_pack_id}
                  >
                    <input
                      checked={selected}
                      className="sr-only"
                      name="review-pack"
                      onChange={() => setSelectedPackId(pack.review_pack_id)}
                      type="radio"
                      value={pack.review_pack_id}
                    />
                    <span className="flex items-start justify-between gap-3">
                      <span className="min-w-0">
                        <span className="block text-xs font-medium tracking-wide text-text-muted uppercase">
                          {pack.company_name}
                        </span>
                        <span className="mt-1 block font-semibold">{pack.display_name}</span>
                      </span>
                      {selected ? (
                        <CheckCircle2 aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" />
                      ) : null}
                    </span>
                    <span className="mt-2 block text-xs text-text-muted">
                      {pack.document_type} · версия {pack.version}
                    </span>
                    <span className="mt-2 block text-sm leading-6 text-text-secondary">
                      {pack.description}
                    </span>
                  </label>
                );
              })}
            </fieldset>
          ) : null}
        </section>

        <input
          accept={ACCEPTED_FILES}
          aria-hidden="true"
          className="sr-only"
          disabled={phase === "uploading"}
          onChange={(event) => chooseFile(event.target.files?.[0])}
          ref={inputRef}
          tabIndex={-1}
          type="file"
        />
        <div
          aria-label="Область загрузки документа"
          className={cn(
            "group flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-(--radius-card) border-2 border-dashed px-4 py-8 text-center transition-colors sm:min-h-64 sm:px-6 sm:py-10",
            dragging
              ? "border-primary bg-primary/5"
              : "border-border bg-muted/35 hover:border-primary/50 hover:bg-primary/[0.03] active:border-primary/50 active:bg-primary/[0.05]",
            phase === "uploading" && "cursor-wait",
          )}
          onClick={openPicker}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openPicker();
            }
          }}
          role="button"
          tabIndex={0}
        >
          {file ? (
            <>
              <span className="grid size-12 place-items-center rounded-(--radius-card) bg-primary/10 text-primary sm:size-14">
                <FileText aria-hidden="true" className="size-6 sm:size-7" />
              </span>
              <p className="mt-4 max-w-full truncate font-semibold">{file.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{formatBytes(file.size)}</p>
            </>
          ) : (
            <>
              <span className="grid size-12 place-items-center rounded-(--radius-card) bg-primary/10 text-primary sm:size-14">
                <UploadCloud aria-hidden="true" className="size-6 sm:size-7" />
              </span>
              {/* Пальцем файл не перетаскивают: на тач-экране обещаем то, что работает */}
              <p className="mt-4 font-semibold pointer-coarse:hidden">Перетащите файл сюда</p>
              <p className="mt-1 text-sm text-muted-foreground pointer-coarse:hidden">
                или нажмите, чтобы выбрать
              </p>
              <p className="mt-4 hidden font-semibold pointer-coarse:block">
                Нажмите, чтобы выбрать файл
              </p>
            </>
          )}
        </div>

        {phase === "uploading" && (
          <div aria-live="polite" className="mt-5">
            <div className="mb-2 flex justify-between text-sm font-medium">
              <span>Загружаем документ</span>
              <span>{progress}%</span>
            </div>
            <div
              aria-label="Прогресс загрузки"
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progress}
              className="h-2 overflow-hidden rounded-full bg-muted"
              role="progressbar"
            >
              <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {message && (
          <div
            aria-live="polite"
            className="mt-5 flex gap-3 rounded-(--radius-sm) bg-red-soft px-4 py-3 text-sm leading-6 text-red"
          >
            <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{message}</span>
          </div>
        )}

        {(phase === "success" || phase === "starting") && receipt && (
          <div
            aria-live="polite"
            className="mt-5 flex gap-3 rounded-(--radius-sm) bg-green-soft px-4 py-3 text-sm text-green"
          >
            <CheckCircle2 aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>Документ загружен. Проверка занимает около минуты.</span>
          </div>
        )}

        {file && phase !== "uploading" && (
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <Button className="w-full sm:w-auto" onClick={openPicker} type="button" variant="secondary">
              <RefreshCw aria-hidden="true" className="size-4" />
              Заменить файл
            </Button>
            {phase === "success" || phase === "starting" ? (
              <Button
                className="w-full sm:w-auto"
                disabled={phase === "starting" || !selectedPackId}
                onClick={() => void startReview()}
                type="button"
              >
                {phase === "starting" ? "Запускаем проверку" : "Проверить документ"}
              </Button>
            ) : (
              <Button className="w-full sm:w-auto" onClick={() => void startUpload()} type="button">
                Загрузить документ
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
