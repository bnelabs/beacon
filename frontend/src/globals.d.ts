/**
 * Ambient declarations for build-time globals injected by Vite's `define`
 * (see vite.config.js). These are replaced at build time, so they are not
 * real runtime bindings the bundler can see -- TypeScript needs them declared
 * to typecheck the `.tsx` modules that reference them.
 */

/** The package version, injected as a string literal by vite.config.js. */
declare const __APP_VERSION__: string
