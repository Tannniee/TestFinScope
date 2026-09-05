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

/**
 * Extract 2-letter uppercase initials from merchant or entity name.
 */
export function getMerchantInitials(name) {
  if (!name) return 'TX';
  const clean = String(name).trim().replace(/^[^a-zA-Z0-9]+/, '');
  if (!clean) return 'TX';
  const words = clean.split(/\s+/);
  if (words.length >= 2 && words[0].length > 0 && words[1].length > 0) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return clean.slice(0, 2).toUpperCase();
}

/**
 * Animate numerical count-up transition on an element.
 * @param {HTMLElement} el
 * @param {number} endValue
 * @param {Object} [options]
 */
export function animateCountUp(el, endValue, options = {}) {
  if (!el || isNaN(endValue)) return;
  const duration = options.duration || 600;
  const formatter = options.formatter || ((v) => `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
  const startTime = performance.now();
  const startValue = options.startValue !== undefined ? options.startValue : 0;

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease out cubic
    const ease = 1 - Math.pow(1 - progress, 3);
    const currentVal = startValue + (endValue - startValue) * ease;
    el.textContent = formatter(currentVal);

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      el.textContent = formatter(endValue);
    }
  }

  requestAnimationFrame(update);
}
