/// <reference types="vite/client" />

/**
 * Types the environment variables this app reads.
 *
 * Without it `import.meta.env.VITE_API_BASE_URL` is `any`, so a typo in the
 * name silently yields `undefined` and the app quietly calls the wrong host.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
