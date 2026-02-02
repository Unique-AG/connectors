/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_URL: string;
  readonly VITE_POWERSYNC_URL: string;
  readonly VITE_IMAGEKIT_ENDPOINT: string;
}

export interface ImportMeta {
  readonly env: ImportMetaEnv;
}
