/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_ENV?: "development" | "test" | "demo" | "production";
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_API_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
