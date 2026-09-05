import {
  ArrowDown,
  ArrowLeftRight,
  BookOpenCheck,
  Boxes,
  Building2,
  CheckCircle2,
  Clock3,
  FileInput,
  MessageSquareText,
  RotateCcw,
  ServerCog,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

type ArchitectureStatus = "implemented" | "roadmap";

interface ArchitectureStageProps {
  eyebrow: string;
  title: string;
  description: string;
  details: string[];
  icon: LucideIcon;
  status?: ArchitectureStatus;
}

const roadmapItems = [
  {
    title: "Самообслуживание компаний",
    text: "Загрузка, проверка и публикация Review Pack через административный интерфейс.",
  },
  {
    title: "Управление доступом",
    text: "SSO, роли и отдельные пространства для нескольких организаций и команд.",
  },
  {
    title: "Улучшение правил по обратной связи",
    text: "Рекомендации по новой версии пакета на основе подтверждённых и отклонённых замечаний.",
  },
];

function StatusLabel({ status }: { status: ArchitectureStatus }) {
  const implemented = status === "implemented";
  const Icon = implemented ? CheckCircle2 : Clock3;
  return (
    <span
      className={
        implemented
          ? "inline-flex items-center gap-1.5 rounded-full bg-green-soft px-2.5 py-1 text-xs font-semibold text-green"
          : "inline-flex items-center gap-1.5 rounded-full bg-amber-soft px-2.5 py-1 text-xs font-semibold text-amber"
      }
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {implemented ? "Реализовано" : "Roadmap"}
    </span>
  );
}

function ArchitectureStage({
  eyebrow,
  title,
  description,
  details,
  icon: Icon,
  status = "implemented",
}: ArchitectureStageProps) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-(--radius-sm) bg-accent-soft text-accent">
          <Icon aria-hidden="true" className="size-5" />
        </span>
        <StatusLabel status={status} />
      </div>
      <p className="mt-4 text-xs font-semibold tracking-wide text-text-muted uppercase">
        {eyebrow}
      </p>
      <h2 className="mt-1 text-lg font-semibold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-text-secondary">{description}</p>
      <ul className="mt-4 space-y-2 text-sm leading-6 text-text-secondary">
        {details.map((detail) => (
          <li className="flex gap-2" key={detail}>
            <span aria-hidden="true" className="mt-[0.65rem] size-1.5 shrink-0 rounded-full bg-accent" />
            <span>{detail}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function FlowArrow({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center py-2 text-text-muted" role="img" aria-label={label}>
      <ArrowDown aria-hidden="true" className="size-5" />
    </div>
  );
}

export function ArchitecturePage() {
  return (
    <div className="space-y-8 sm:space-y-10">
      <PageHeader
        eyebrow="Архитектура платформы"
        title="Одно приложение для разных стандартов документации"
        description="Компания передаёт свои правила как версионируемый пакет знаний. Приложение, ядро анализа и модельный шлюз остаются общими для всех профилей."
      />

      <div aria-label="Статусы компонентов" className="flex flex-wrap gap-2">
        <StatusLabel status="implemented" />
        <StatusLabel status="roadmap" />
      </div>

      <section aria-label="Поток данных платформы">
        <ArchitectureStage
          description="Организация описывает собственный стандарт документа и допустимые исключения без изменения кода продукта."
          details={["Manifest и тип документа", "Шаблон, таксономия и глоссарий"]}
          eyebrow="Company Inputs"
          icon={Building2}
          title="Знания организации"
        />

        <FlowArrow label="Знания организации собираются в Review Pack" />

        <ArchitectureStage
          description="Сервер проверяет пакет, регистрирует его версию в каталоге и не раскрывает внутренний путь пользователю."
          details={["Безопасный каталог разрешённых пакетов", "Выбор профиля перед запуском проверки"]}
          eyebrow="Review Pack"
          icon={BookOpenCheck}
          title="Версионируемый пакет знаний"
        />

        <FlowArrow label="Review Pack передаётся ядру анализа" />

        <div className="grid items-stretch gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
          <ArchitectureStage
            description="Отдельный CLI принимает документ и пакет, объединяет формальные правила с модельным анализом и возвращает ReviewResult JSON."
            details={["Детерминированные проверки", "До 20 проверенных замечаний"]}
            eyebrow="Analysis Core"
            icon={Boxes}
            title="Единое ядро анализа"
          />
          <div
            aria-label="Ядро обращается к модельному шлюзу"
            className="flex items-center justify-center text-text-muted"
            role="img"
          >
            <ArrowLeftRight aria-hidden="true" className="size-5 rotate-90 sm:rotate-0" />
          </div>
          <ArchitectureStage
            description="Модель работает внутри инфраструктуры организации; адрес и параметры передаются ядру серверной конфигурацией."
            details={["Ollama совместимый API", "Qwen в закрытом контуре"]}
            eyebrow="On-premise Model Gateway"
            icon={ServerCog}
            title="Локальная языковая модель"
          />
        </div>

        <FlowArrow label="Результат ядра поступает в приложение" />

        <ArchitectureStage
          description="Один интерфейс управляет документами, асинхронными проверками и результатами независимо от выбранной таксономии."
          details={["Загрузка, очередь и история", "Место ошибки и возможная корректировка"]}
          eyebrow="Product Application"
          icon={FileInput}
          title="Приложение для аналитика"
        />

        <FlowArrow label="Оценки пользователя формируют обратную связь" />

        <ArchitectureStage
          description="Решение аналитика сохраняется рядом с находкой и используется для оценки качества конкретной версии пакета."
          details={["Принято, отклонено или требует уточнения", "Метрики и экспорт разметки"]}
          eyebrow="Feedback Loop"
          icon={MessageSquareText}
          title="Контур обратной связи"
        />

        <div className="mt-3 flex items-start gap-3 rounded-(--radius-sm) bg-accent-bg px-4 py-3 text-sm leading-6 text-text-secondary">
          <RotateCcw aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent" />
          <p>
            Обратная связь возвращается владельцу знаний: он обновляет Review Pack, публикует
            новую версию и не меняет код приложения или ядра.
          </p>
        </div>
      </section>

      <section aria-labelledby="architecture-roadmap">
        <div className="mb-4 flex items-center gap-3">
          <Clock3 aria-hidden="true" className="size-5 text-amber" />
          <h2 className="text-xl font-semibold" id="architecture-roadmap">
            Следующие шаги платформы
          </h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {roadmapItems.map((item) => (
            <article className="rounded-(--radius-sm) border border-border bg-card p-4" key={item.title}>
              <StatusLabel status="roadmap" />
              <h3 className="mt-3 font-semibold">{item.title}</h3>
              <p className="mt-2 text-sm leading-6 text-text-secondary">{item.text}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
