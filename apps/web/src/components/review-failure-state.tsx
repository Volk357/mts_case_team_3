import { CircleX, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";

import type { ReviewState } from "@/api/reviews";
import { ErrorReference } from "@/components/error-reference";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface FailureCopy {
  title: string;
  message: string;
}

const FAILURE_COPY: Record<string, FailureCopy> = {
  DOCUMENT_READ_ERROR: {
    title: "Документ не удалось прочитать",
    message: "Проверьте файл и загрузите документ повторно.",
  },
  DOCUMENT_PARSE_ERROR: {
    title: "Документ не удалось разобрать",
    message: "Структура файла повреждена или не поддерживается. Попробуйте другую версию файла.",
  },
  UNSUPPORTED_DOCUMENT: {
    title: "Формат документа не поддерживается",
    message: "Сохраните документ в PDF или DOCX и запустите новую проверку.",
  },
  REVIEW_PACK_NOT_FOUND: {
    title: "Профиль проверки недоступен",
    message: "Выберите актуальный профиль на стартовой странице и запустите проверку повторно.",
  },
  REVIEW_PACK_INVALID: {
    title: "Профиль проверки некорректен",
    message: "Выберите другой доступный профиль или обратитесь к администратору продукта.",
  },
  REVIEW_PACK_INCOMPATIBLE: {
    title: "Профиль проверки несовместим",
    message: "Для новой проверки выберите профиль, совместимый с текущей версией продукта.",
  },
  CORE_PROCESS_FAILED: {
    title: "Модуль анализа недоступен",
    message: "Не удалось выполнить анализ документа. Попробуйте запустить проверку позднее.",
  },
  WORKER_EXECUTION_ERROR: {
    title: "Модуль анализа недоступен",
    message: "Не удалось выполнить анализ документа. Попробуйте запустить проверку позднее.",
  },
  WORKER_INTERRUPTED: {
    title: "Анализ был прерван",
    message: "Запустите новую проверку документа.",
  },
  MODEL_UNAVAILABLE: {
    title: "Модель анализа временно недоступна",
    message: "Документ сохранён, но анализ выполнить не удалось. Повторите проверку позднее.",
  },
  MODEL_TIMEOUT: {
    title: "Модель анализа не ответила вовремя",
    message: "Попробуйте запустить проверку повторно.",
  },
  MODEL_AUTH_FAILED: {
    title: "Нет доступа к модели анализа",
    message: "Обратитесь к администратору продукта и повторите проверку после восстановления доступа.",
  },
  MODEL_CONFIG_INVALID: {
    title: "Модель анализа не настроена",
    message: "Обратитесь к администратору продукта.",
  },
  ANALYSIS_TIMEOUT: {
    title: "Превышено время проверки",
    message: "Анализ остановлен по тайм-ауту. Попробуйте запустить проверку повторно.",
  },
  CORE_SCHEMA_INCOMPATIBLE: {
    title: "Версия результата не поддерживается",
    message: "Результат не был показан, чтобы избежать некорректных замечаний.",
  },
  CORE_RESULT_INVALID: {
    title: "Результат проверки несовместим",
    message: "Модуль анализа вернул результат в неподдерживаемом формате.",
  },
  CORE_RESULT_MISMATCH: {
    title: "Результат проверки не принят",
    message: "Полученный результат относится к другому запуску и не будет показан.",
  },
  MODEL_RESPONSE_INVALID: {
    title: "Результат модели не принят",
    message: "Модель вернула некорректный результат. Попробуйте запустить проверку повторно.",
  },
  ANALYSIS_CANCELLED: {
    title: "Проверка отменена",
    message: "При необходимости запустите новую проверку документа.",
  },
};

function failureCopy(review: ReviewState): FailureCopy {
  if (review.status === "timed_out") return FAILURE_COPY.ANALYSIS_TIMEOUT;
  if (review.status === "cancelled") return FAILURE_COPY.ANALYSIS_CANCELLED;
  return (
    FAILURE_COPY[review.error?.code ?? ""] ?? {
      title: "Неизвестная ошибка проверки",
      message: "Запустите проверку повторно. Если ошибка сохранится, передайте код обращения поддержке.",
    }
  );
}

export function ReviewFailureState({
  review,
  correlationId,
}: {
  review: ReviewState;
  correlationId?: string;
}) {
  const copy = failureCopy(review);

  return (
    <Card aria-live="polite" className="border-danger/20 p-6 sm:p-8" role="alert">
      <div className="flex gap-4">
        <CircleX aria-hidden="true" className="mt-0.5 size-7 shrink-0 text-danger" />
        <div>
          <h2 className="text-lg font-semibold">{copy.title}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{copy.message}</p>
          <ErrorReference correlationId={correlationId} />
        </div>
      </div>
      <Button asChild className="mt-5" size="sm" variant="secondary">
        <Link to="/">
          <RotateCcw aria-hidden="true" className="size-4" />
          Запустить новую проверку
        </Link>
      </Button>
    </Card>
  );
}
