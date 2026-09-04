import { ArrowDown, Building2, FileSearch, ShieldCheck } from "lucide-react";

import { FileDropzone } from "@/components/file-dropzone";
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
  return (
    <div className="space-y-12">
      <section className="max-w-3xl space-y-6 py-8">
        <h1 className="max-w-3xl text-[2.75rem] leading-[1.15] font-semibold tracking-tight">
          Найдите вопросы к документу до передачи в разработку
        </h1>
        <p className="max-w-2xl text-lg leading-8 text-text-secondary">
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

      <section aria-label="Загрузка документа" className="max-w-3xl">
        <FileDropzone />
      </section>

      <section aria-label="Преимущества" className="grid gap-4 md:grid-cols-3">
        {benefits.map(({ icon: Icon, title, text }) => (
          <Card className="p-6" key={title}>
            <Icon aria-hidden="true" className="mb-5 size-5 text-accent" />
            <h2 className="mb-2 font-semibold">{title}</h2>
            <p className="text-sm leading-6 text-text-secondary">{text}</p>
          </Card>
        ))}
      </section>
    </div>
  );
}
