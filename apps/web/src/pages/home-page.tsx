import { ArrowDown, Building2, FileSearch, ShieldCheck } from "lucide-react";

import { FileDropzone } from "@/components/file-dropzone";
import { Button } from "@/components/ui/button";

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
    text: "Архитектура поддерживает модели, развёрнутые внутри вашей инфраструктуры.",
  },
];

export function HomePage() {
  return (
    <div className="space-y-10 sm:space-y-14">
      <section className="space-y-5 sm:space-y-6 sm:py-4">
        <h1 className="max-w-2xl text-display font-semibold text-balance">
          Найдите вопросы к документу до передачи в разработку
        </h1>
        <p className="text-lead max-w-2xl text-text-secondary">
          DocReview проверяет готовый документ по правилам вашей организации и показывает, где
          информации недостаточно для однозначной реализации.
        </p>
        {/* На телефоне область загрузки и так следующая на экране — якорь там лишний */}
        <Button asChild className="hidden sm:inline-flex">
          <a href="#upload">
            Начать проверку
            <ArrowDown aria-hidden="true" className="size-4" />
          </a>
        </Button>
      </section>

      <section aria-label="Загрузка документа">
        <FileDropzone />
      </section>

      {/* Не карточки: три коротких утверждения на общем фоне читаются подряд
          и на узком экране не превращаются в три одинаковых плитки. */}
      <section aria-label="Как устроена проверка">
        <dl className="grid gap-px overflow-hidden rounded-(--radius-card) border border-border bg-border sm:grid-cols-3">
          {benefits.map(({ icon: Icon, title, text }) => (
            <div className="bg-card p-5 sm:p-6" key={title}>
              <Icon aria-hidden="true" className="mb-4 size-5 text-accent" />
              <dt className="mb-1.5 font-semibold">{title}</dt>
              <dd className="text-sm leading-6 text-text-secondary">{text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
