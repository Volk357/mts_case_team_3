export type AppEnvironment = "development" | "test" | "demo" | "production";

const supportedEnvironments = new Set<AppEnvironment>([
  "development",
  "test",
  "demo",
  "production",
]);

function readEnvironment(value: string | undefined): AppEnvironment {
  const environment = value ?? "development";
  if (!supportedEnvironments.has(environment as AppEnvironment)) {
    throw new Error(`Unsupported VITE_APP_ENV: ${environment}`);
  }
  return environment as AppEnvironment;
}

function readApiBaseUrl(value: string | undefined): string {
  const apiBaseUrl = (value ?? "").trim().replace(/\/$/, "");
  if (apiBaseUrl && !apiBaseUrl.startsWith("/") && !/^https?:\/\//.test(apiBaseUrl)) {
    throw new Error("VITE_API_BASE_URL must be an HTTP(S) URL or an absolute path");
  }
  return apiBaseUrl;
}

export const appConfig = Object.freeze({
  environment: readEnvironment(import.meta.env.VITE_APP_ENV),
  apiBaseUrl: readApiBaseUrl(import.meta.env.VITE_API_BASE_URL),
});
