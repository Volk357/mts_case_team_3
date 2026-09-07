import { afterEach, expect, it, vi } from "vitest";

import { newRequestId } from "@/lib/request-id";

afterEach(() => vi.unstubAllGlobals());

// Контур раздаётся по http, а это НЕ защищённый контекст: `crypto.randomUUID`
// там отсутствует. Прежний код вызывал его напрямую, падал с TypeError до
// отправки запроса — и проверку нельзя было запустить из интерфейса вовсе.
// Тесты этого не ловили: Playwright работает на localhost, а localhost
// считается защищённым контекстом.
it("выдаёт ключ, когда randomUUID недоступен (http-контур)", () => {
  vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(7) });
  const id = newRequestId();
  expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

it("выдаёт ключ, когда недоступен и getRandomValues", () => {
  vi.stubGlobal("crypto", {});
  expect(newRequestId().length).toBeGreaterThan(8);
});

it("использует randomUUID, когда он есть", () => {
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-2222-4333-8444-555555555555" });
  expect(newRequestId()).toBe("11111111-2222-4333-8444-555555555555");
});

it("не повторяется", () => {
  vi.stubGlobal("crypto", {});
  expect(new Set(Array.from({ length: 50 }, newRequestId)).size).toBe(50);
});
