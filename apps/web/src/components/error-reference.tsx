export function ErrorReference({ correlationId }: { correlationId?: string }) {
  if (!correlationId) return null;

  return (
    <p className="mt-3 text-xs text-muted-foreground">
      Код обращения: <code className="break-all select-all">{correlationId}</code>
    </p>
  );
}
