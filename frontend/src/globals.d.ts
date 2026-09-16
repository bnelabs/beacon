/**
 * Ambient declarations for build-time globals injected by Vite's `define`
 * (see vite.config.js). These are replaced at build time, so they are not
 * real runtime bindings the bundler can see -- TypeScript needs them declared
 * to typecheck the `.tsx` modules that reference them.
 */

/** The package version, injected as a string literal by vite.config.js. */
declare const __APP_VERSION__: string

// Note on static JSON imports: `moduleResolution: "bundler"` implies
// `resolveJsonModule`, so the two Natural Earth payloads
// (`data/world-countries.json`, `data/region-boundaries.json`) that the risk
// map dynamically imports are typed from their real contents. Their inferred
// `type: string` widens past the `"FeatureCollection"` literal deck.gl's
// `GeoJsonLayer` expects, so RiskMap casts them to `FeatureCollection` from
// `geojson` (@types/geojson ships with the deck.gl type surface).
