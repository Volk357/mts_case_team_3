const STORAGE_KEY = "docreview.feedback-actor-key";
let memoryActorKey: string | undefined;

function createActorKey(): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `web-analyst-${suffix}`;
}

export function getFeedbackActorKey(): string {
  if (memoryActorKey) return memoryActorKey;

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      memoryActorKey = stored;
      return stored;
    }
    memoryActorKey = createActorKey();
    window.localStorage.setItem(STORAGE_KEY, memoryActorKey);
    return memoryActorKey;
  } catch {
    memoryActorKey = createActorKey();
    return memoryActorKey;
  }
}
