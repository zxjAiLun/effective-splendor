/**
 * The one Studio Host base URL.
 *
 * Every page in this app talks to the same local Host, and the Host's CORS header
 * allows exactly one origin, so this value used to be copied into five pages. A
 * sixth copy for the League page would have been worse than one shared module.
 *
 * This is a de-duplication, not a configuration system: no port discovery,
 * no runtime settings. The Host port is a fact of how the operator starts the
 * Host (`--port`), and the app is expected to match it.
 *
 * The one deployment seam: a public build served behind a same-origin reverse
 * proxy (e.g. https://pearllover.site/splendor/api -> 127.0.0.1:43120) sets
 * VITE_STUDIO_API_BASE at build time. Unset keeps the local behavior above.
 * BASE_PATH carries the same deployment's UI subpath for the few navigations
 * that bypass next/link and assign window.location directly.
 */
export const API_BASE = import.meta.env?.VITE_STUDIO_API_BASE || "http://127.0.0.1:43120";

export const BASE_PATH = import.meta.env?.VITE_STUDIO_BASE_PATH || "";
