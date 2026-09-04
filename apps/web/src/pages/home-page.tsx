import {
  ArrowDown,
  Building2,
  CheckCircle2,
  CircleAlert,
  FileSearch,
  LoaderCircle,
  PencilOff,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import type { DocumentUploadResponse } from "@/api/documents";
import { createReview } from "@/api/reviews";
import { ErrorReference } from "@/components/error-reference";
import { FileDropzone } from "@/components/file-dropzone";
import { ReviewPackSelector } from "@/components/review-pack-selector";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const benefits = [
  {
    icon: FileSearch,
    title: "Конкретные замечания",
    text: "Каждая находка привязана к разделу и фрагменту документа.",
  },
  {
    icon: Building2,
    title: "Правила вашей компании",
    text: "Профиль проверки подключается через версионируемый Review Pack.",
  },
  {
    icon: ShieldCheck,
    title: "Закрытый контур",
    text: "Архитектура поддерживает внутренние OpenAI-совместимые модели.",
  },
];

type SubmissionState =
  | { kind: "idle" }
  | { kind: "creating" }
  | { kind: "success"; reviewId: string }
  | { kind: "error"; message: string; correlationId?: string };

function reviewErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Не удалось подключиться к серверу. Повторите запуск.";
    if (error.code === "REVIEW_PACK_NOT_FOUND") {
      return "Выбранный профиль проверки больше недоступен. Выберите другой профиль.";
    }
    if (error.code === "DOCUMENT_NOT_FOUND") {
      return "Загруженный документ больше недоступен. Загрузите его повторно.";
    }
  }
  return "Не удалось запустить проверку. Попробуйте ещё раз.";
}

export function HomePage() {
  const navigate = useNavigate();
  const [reviewPackId, setReviewPackId] = useState("");
  const [uploadedDocument, setUploadedDocument] = useState<DocumentUploadResponse | null>(null);
  const [submission, setSubmission] = useState<SubmissionState>({ kind: "idle" });
  const [resetToken, setResetToken] = useState(0);
  const [isUploading, setIsUploading] = useState(false);

  const startReview = async (document: DocumentUploadResponse) => {
    if (!reviewPackId || submission.kind === "creating") return;
    setSubmission({ kind: "creating" });
    try {
      const review = await createReview(
        document.document_id,
        reviewPackId,
        `web-${document.document_id}-${reviewPackId}`,
      );
      setUploadedDocument(null);
      setReviewPackId("");
      setResetToken((current) => current + 1);
      setSubmission({ kind: "success", reviewId: review.review_id });
      void navigate(`/reviews/${encodeURIComponent(review.review_id)}`);
    } catch (error) {
      setSubmission({
        kind: "error",
        message: reviewErrorMessage(error),
        correlationId: error instanceof ApiError ? error.correlationId : undefined,
      });
    }
  };

  const onUploadComplete = (document: DocumentUploadResponse) => {
    setUploadedDocument(document);
    void startReview(document);
  };

  return (
    <div className="space-y-8 sm:space-y-12">
      <section className="max-w-3xl space-y-6 py-4 sm:py-8">
        <div className="inline-flex rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-sm font-medium text-primary">
          Quality gate для корпоративной документации
        </div>
        <h1 className="text-4xl leading-tight font-semibold tracking-tight text-balance sm:text-5xl">
          Найдите вопросы к документу до передачи в разработку
        </h1>
        <p className="max-w-2xl text-lg leading-8 text-muted-foreground">
          DocReview проверяет готовый документ по правилам вашей организации и показывает, где
          информации недостаточно для однозначной реализации.
        </p>
        <Button asChild>
          <a href="#upload">
            Загрузить документ
            <ArrowDown aria-hidden="true" className="size-4" />
          </a>
        </Button>
      </section>

      <section aria-label="Подготовка проверки" className="max-w-3xl space-y-6">
        <ReviewPackSelector
          disabled={isUploading || submission.kind === "creating"}
          onChange={setReviewPackId}
          value={reviewPackId}
        />
        <FileDropzone
          key={resetToken}
          onSelectionChange={() => {
            setUploadedDocument(null);
            setSubmission({ kind: "idle" });
          }}
          onUploadComplete={onUploadComplete}
          onUploadStateChange={setIsUploading}
          uploadAllowed={Boolean(reviewPackId) && submission.kind !== "creating"}
          uploadBlockedReason="Сначала выберите профиль проверки."
        />
        {submission.kind === "creating" && (
          <div aria-live="polite" className="flex items-center gap-3 rounded-xl bg-primary/5 px-4 py-3 text-sm text-primary">
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
            Документ загружен. Создаём проверку…
          </div>
        )}
        {submission.kind === "error" && (
          <div className="space-y-3 rounded-xl bg-danger/10 px-4 py-3" role="alert">
            <div className="flex gap-3 text-sm text-danger">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>{submission.message}</span>
            </div>
            <ErrorReference correlationId={submission.correlationId} />
            {uploadedDocument && (
              <Button
                onClick={() => void startReview(uploadedDocument)}
                size="sm"
                type="button"
                variant="secondary"
              >
                <RefreshCw aria-hidden="true" className="size-4" />
                Повторить запуск
              </Button>
            )}
          </div>
        )}
        {submission.kind === "success" && (
          <div aria-live="polite" className="flex gap-3 rounded-xl bg-success/10 px-4 py-3 text-sm text-success">
            <CheckCircle2 aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>
              Проверка запущена. Идентификатор: <code>{submission.reviewId}</code>
            </span>
          </div>
        )}
        <div className="flex gap-3 rounded-2xl border border-primary/15 bg-primary/5 px-5 py-4">
          <PencilOff aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Исходный документ останется без изменений</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              DocReview только укажет место замечания и возможную корректировку. Решение об
              изменении текста всегда принимает аналитик.
            </p>
          </div>
        </div>
      </section>

      <section aria-label="Преимущества" className="grid gap-4 md:grid-cols-3">
        {benefits.map(({ icon: Icon, title, text }) => (
          <Card className="p-6" key={title}>
            <Icon aria-hidden="true" className="mb-5 size-6 text-primary" />
            <h2 className="mb-2 font-semibold">{title}</h2>
            <p className="text-sm leading-6 text-muted-foreground">{text}</p>
          </Card>
        ))}
      </section>
    </div>
  );
}
