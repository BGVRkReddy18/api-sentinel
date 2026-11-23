export function parseTime(value) {
  if (!value) return null;
  // Backend timestamps are UTC; SQLite returns them without an offset.
  const text = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const time = new Date(text);
  return Number.isNaN(time.getTime()) ? null : time;
}

export function timeAgo(value, now = Date.now()) {
  const time = parseTime(value);
  if (!time) return "never";
  const seconds = Math.max(0, Math.round((now - time.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function timeUntil(value, now = Date.now()) {
  const time = parseTime(value);
  if (!time) return "";
  const minutes = Math.max(0, Math.round((time.getTime() - now) / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d`;
}

export function formatMs(value) {
  if (value === null || value === undefined) return "–";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${Math.round(value)} ms`;
}

export function formatPct(value, digits = 2) {
  if (value === null || value === undefined) return "–";
  return `${Number(value).toFixed(digits)}%`;
}

export function formatDateTime(value) {
  const time = parseTime(value);
  return time ? time.toLocaleString([], { dateStyle: "medium", timeStyle: "medium" }) : "–";
}

export function formatTime(value) {
  const time = parseTime(value);
  return time ? time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–";
}

export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function daysUntil(value, now = Date.now()) {
  const time = parseTime(value);
  return time ? Math.floor((time.getTime() - now) / 86400000) : null;
}

export function isInMaintenance(endpoint, now = Date.now()) {
  const until = parseTime(endpoint?.maintenance_until);
  return Boolean(until && until.getTime() > now);
}

/** Effective display status: paused / maintenance override the health status. */
export function displayStatus(endpoint, now = Date.now()) {
  if (!endpoint) return "unknown";
  if (!endpoint.is_active) return "paused";
  if (isInMaintenance(endpoint, now)) return "maintenance";
  return endpoint.current_status;
}
