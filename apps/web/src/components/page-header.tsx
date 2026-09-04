import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
}

export function PageHeader({ eyebrow, title, description }: PageHeaderProps) {
  return (
    <header>
      {eyebrow && <p className="mb-2 text-sm font-semibold text-primary">{eyebrow}</p>}
      <h1 className="text-3xl font-semibold tracking-tight text-balance">{title}</h1>
      {description && (
        <p className="mt-3 max-w-2xl leading-7 text-muted-foreground">{description}</p>
      )}
    </header>
  );
}
