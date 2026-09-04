import { ArrowDown, Building2, FileSearch, PencilOff, ShieldCheck } from "lucide-react";
import { useState } from "react";

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

export function HomePage() {
  const [reviewPackId, setReviewPackId] = useState("");

  return (
    <div className="space-y-12">
      <section className="max-w-3xl space-y-6 py-8">
        <div className="inline-flex rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-sm font-medium text-primary">
          Quality gate для корпоративной документации
        </div>
        <h1 className="text-5xl leading-tight font-semibold tracking-tight">
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
        <ReviewPackSelector onChange={setReviewPackId} value={reviewPackId} />
        <FileDropzone
          uploadAllowed={Boolean(reviewPackId)}
          uploadBlockedReason="Сначала выберите профиль проверки."
        />
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
