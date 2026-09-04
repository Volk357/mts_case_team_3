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
import { getReviewPacks } from "@/api/review-packs";
import { createReview } from "@/api/reviews";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { appConfig } from "@/config";
import { cn } from "@/lib/utils";

const PDF_MEDIA_TYPE = "application/pdf";
const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const ACCEPTED_FILES = `${PDF_MEDIA_TYPE},${DOCX_MEDIA_TYPE},.pdf,.docx`;

type UploadPhase = "idle" | "ready" | "uploading" | "success" | "starting" | "error";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function validateFile(file: File): string | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  const expectedType = extension === ".pdf" ? PDF_MEDIA_TYPE : extension === ".docx" ? DOCX_MEDIA_TYPE : null;
  if (!expectedType) return "Выберите документ в формате PDF или DOCX.";
  if (file.type && file.type !== expectedType) {
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
    if (error.status === 415) return "Сервер принимает только PDF и DOCX.";
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
  const navigate = useNavigate();
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => abortRef.current?.abort(), []);

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

  // Загрузка и проверка — один шаг для человека: документ загружают, чтобы
  // его проверили, а не чтобы он лежал. Пакет правил берём первый доступный:
  // выбор профиля появится, когда пакетов станет больше одного.
  const startReview = async () => {
    if (!receipt || phase === "starting") return;
    setPhase("starting");
    setMessage(null);
    try {
      const packs = await getReviewPacks();
      const pack = packs.items[0];
      if (!pack) {
        setPhase("error");
        setMessage("В контуре не настроен ни один профиль проверки. Обратитесь к администратору.");
        return;
      }
      const review = await createReview(
        receipt.document_id,
        pack.review_pack_id,
        crypto.randomUUID(),
      );
      navigate(`/reviews/${review.review_id}`);
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
      <div className="border-b border-border px-6 py-5 sm:px-8">
        <h2 className="text-xl font-semibold">Загрузите документ</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          PDF или DOCX до {formatBytes(appConfig.maxUploadSizeBytes)}
        </p>
      </div>
      <div className="p-6 sm:p-8">
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
            "group flex min-h-64 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "border-border bg-muted/35 hover:border-primary/50 hover:bg-primary/[0.03]",
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
              <span className="grid size-14 place-items-center rounded-2xl bg-primary/10 text-primary">
                <FileText aria-hidden="true" className="size-7" />
              </span>
              <p className="mt-4 max-w-full truncate font-semibold">{file.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{formatBytes(file.size)}</p>
            </>
          ) : (
            <>
              <span className="grid size-14 place-items-center rounded-2xl bg-primary/10 text-primary">
                <UploadCloud aria-hidden="true" className="size-7" />
              </span>
              <p className="mt-4 font-semibold">Перетащите файл сюда</p>
              <p className="mt-1 text-sm text-muted-foreground">или нажмите, чтобы выбрать</p>
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
          <div aria-live="polite" className="mt-5 flex gap-3 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
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
            <Button onClick={openPicker} type="button" variant="secondary">
              <RefreshCw aria-hidden="true" className="size-4" />
              Заменить файл
            </Button>
            {phase === "success" || phase === "starting" ? (
              <Button disabled={phase === "starting"} onClick={() => void startReview()} type="button">
                {phase === "starting" ? "Запускаем проверку" : "Проверить документ"}
              </Button>
            ) : (
              <Button onClick={() => void startUpload()} type="button">
                Загрузить документ
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
