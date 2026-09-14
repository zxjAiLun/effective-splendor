/**
 * The one Studio Host base URL.
 *
 * Every page in this app talks to the same local Host, and the Host's CORS header
 * allows exactly one origin, so this value used to be copied into five pages. A
 * sixth copy for the League page would have been worse than one shared module.
 *
 * This is a de-duplication, not a configuration system: no environment variable,
 * no port discovery, no proxy, no runtime settings. The Host port is a fact of how
 * the operator starts the Host (`--port`), and the app is expected to match it.
 */
export const API_BASE = "http://127.0.0.1:43120";
