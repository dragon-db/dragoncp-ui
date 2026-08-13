/**
 * Values Vite substitutes at build time.
 *
 * `__APP_VERSION__` is read from the repository's `VERSION` file by
 * `vite.config.ts`, which is the same file `config.py` reads. Declared here so
 * it is a real constant to TypeScript rather than a global nobody typed.
 */
declare const __APP_VERSION__: string;
