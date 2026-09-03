import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { App } from "@/app";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Health page", () => {
  it("shows backend version after a successful health check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "ok",
            service: "DocReview API",
            environment: "test",
            version: "0.1.0",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/debug/health"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Backend доступен")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
  });

  it("shows an error when the backend is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection refused")));

    render(
      <MemoryRouter initialEntries={["/debug/health"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Backend недоступен")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
  });
});
