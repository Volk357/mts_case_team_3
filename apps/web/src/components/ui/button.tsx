import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Своего кольца фокуса у кнопки нет намеренно. Оно было `ring-primary/40` —
  // бирюзовый под 40% прозрачности на светлом фоне даёт контраст ~1.6:1 при
  // норме 3:1 (WCAG 2.2, 1.4.11), и держалось только потому, что базовое
  // правило лежало вне слоя и перебивало отключение обводки. Индикатор фокуса
  // в приложении один — обводка из `@layer base`, 2px accent, контраст 5:1
  // на тёмно-синей шапке и 3.3:1 на светлом фоне.
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-(--radius-sm) text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 active:bg-accent-hover",
        secondary:
          "border border-border bg-card text-foreground hover:bg-muted active:bg-background-subtle",
        ghost: "text-muted-foreground hover:bg-muted hover:text-foreground active:bg-muted",
      },
      size: {
        default: "h-11 px-5",
        // Компактный размер компактен только там, где есть мышь: на тач-экране
        // он всё равно не ниже 44px.
        sm: "h-11 px-3.5 sm:h-9 sm:px-3",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({
  asChild = false,
  className,
  variant,
  size,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : "button";

  return (
    <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />
  );
}
