// Formatting helpers for the widget.
//
// Ported from `albanna`'s side-chat, and portable without a change because
// nothing here is bound to this app's contract: it formats moments and
// numbers, and a moment is a moment. The only thing that is not trivial is
// the relative time, and it is done with `Intl.RelativeTimeFormat` rather
// than a hand-rolled "2 min ago": the formatter follows the browser's
// locale, so an Arabic interface gets "قبل دقيقتين" without a second
// translation table.

/** The locale the interface is in. */
export function currentLocale() {
  if (typeof document !== "undefined" && document.documentElement) {
    const lang = document.documentElement.lang;
    if (lang) return lang;
  }
  if (typeof navigator !== "undefined" && navigator.language) {
    return navigator.language;
  }
  return "en";
}

/**
 * A moment, as a `Date`.
 *
 * The epoch is preferred over the string: the server's timestamps are
 * naive — "2026-10-21 03:20:00", with no timezone — so a browser in a
 * different timezone from the server reads them as a different moment, and
 * a conversation that happened a minute ago reads as "in three hours".
 *
 * @param {number|string|Date} value an epoch in seconds, a timestamp or a Date
 * @returns {Date|null} the moment, or null when it could not be read
 */
function toDate(value) {
  if (!value) return null;

  if (typeof value === "number") {
    return new Date(value * 1000);
  }
  if (value instanceof Date) {
    return value;
  }
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

/**
 * A moment, as "2 minutes ago" / "أمس".
 *
 * @param {number|string|Date} value an epoch in seconds, an ISO timestamp or a Date
 * @returns {string} the relative time
 */
export function relativeTime(value) {
  const date = toDate(value);
  if (!date) return "";

  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units = [
    ["year", 60 * 60 * 24 * 365],
    ["month", 60 * 60 * 24 * 30],
    ["week", 60 * 60 * 24 * 7],
    ["day", 60 * 60 * 24],
    ["hour", 60 * 60],
    ["minute", 60],
    ["second", 1],
  ];

  const formatter = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return formatter.format(Math.round(seconds / size), unit);
    }
  }
  return "";
}

/**
 * A moment, as the reader's clock reads it.
 *
 * @param {number|string|Date} value the moment
 * @returns {string} the local date and time, or "" when unreadable
 */
export function absoluteTime(value) {
  const date = toDate(value);
  if (!date) return "";
  return new Intl.DateTimeFormat(currentLocale(), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/**
 * A number, as the reader's locale writes it.
 *
 * @param {number} value the number
 * @returns {string} the formatted number
 */
export function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return new Intl.NumberFormat(currentLocale()).format(value);
}

/**
 * A byte count, as "1.4 MB".
 *
 * @param {number} bytes the count
 * @returns {string} the human-readable size
 */
export function formatBytes(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 ? 0 : value < 10 ? 1 : 0;
  return `${formatNumber(Number(value.toFixed(digits)))} ${units[unit]}`;
}

/**
 * A character count, as "3 of 8,000 characters".
 *
 * The read tool pages a long file and says where the next part starts, so
 * the panel shows the position rather than only the length — a reader who
 * sees "8,000 characters" and no position cannot tell whether they have
 * read the file.
 *
 * @param {number} returned how many characters this read returned
 * @param {number} total how many the file holds
 * @returns {string} the position
 */
export function formatPosition(returned, total) {
  if (typeof total !== "number" || total <= 0) return "";
  if (typeof returned !== "number" || returned >= total) {
    return `${formatNumber(total)} characters`;
  }
  return `${formatNumber(returned)} of ${formatNumber(total)} characters`;
}
