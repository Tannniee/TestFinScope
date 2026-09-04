/**
 * FinScope Utility Functions
 * Safe HTML escaping to prevent Stored XSS from user-supplied financial data.
 */

export function escapeHtml(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Format a Date object (or date timestamp/string) to YYYY-MM-DD in the local user timezone.
 * Avoids UTC skew bugs from .toISOString().split('T')[0].
 */
export function toLocalDateString(date = new Date()) {
  const d = date instanceof Date ? date : new Date(date);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Returns yesterday's date formatted as YYYY-MM-DD in the local user timezone.
 */
export function localYesterdayString() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return toLocalDateString(d);
}
