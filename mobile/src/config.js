// Default backend address. Change this to your Mac's LAN IP (run
// `ipconfig getifaddr en0` on the Mac) so the phone can reach the server over
// the same Wi-Fi, e.g. "http://192.168.1.23:8000".
//
// You can also override it at runtime in the app's host field on the home
// screen — no rebuild needed.
export const DEFAULT_API_BASE = "http://192.168.1.100:8000";

// How often to poll job status while processing (ms).
export const POLL_INTERVAL_MS = 1500;
