/**
 * Shared Money Formatting Utilities for ECharts and Visualizations.
 * Replaces hardcoded '$' on chart tooltips, value badges, and Y-axis labels.
 */

import { state } from '../state.js';

/**
 * Resolves the localized currency symbol for a given 3-letter currency code.
 * @param {string|null} [curr]
 * @returns {string}
 */
export function getCurrencySymbol(curr = null) {
  const c = curr || state.currency || 'USD';
  try {
    const locale = c === 'VND' ? 'vi-VN' : 'en-US';
    const parts = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: c
    }).formatToParts(0);
    const symPart = parts.find(p => p.type === 'currency');
    return symPart ? symPart.value : c;
  } catch (e) {
    return c;
  }
}

/**
 * Formats a monetary number for chart tooltips or callouts using state.formatCurrency.
 * @param {number} val
 * @param {string|null} [curr]
 * @returns {string}
 */
export function formatChartMoney(val, curr = null) {
  if (val === null || val === undefined || isNaN(val)) return '0';
  return state.formatCurrency(val, curr);
}

/**
 * Compact monetary formatter for chart axis labels (e.g. $1.2k, €5M, 250k ₫).
 * @param {number} val
 * @param {string|null} [curr]
 * @returns {string}
 */
export function formatAxisMoney(val, curr = null) {
  if (val === null || val === undefined || isNaN(val)) return '0';
  const c = curr || state.currency || 'USD';
  const absVal = Math.abs(val);
  const sign = val < 0 ? '-' : '';
  const sym = getCurrencySymbol(c);

  if (c === 'VND') {
    if (absVal >= 1e9) return `${sign}${(absVal / 1e9).toFixed(1)}B ₫`;
    if (absVal >= 1e6) return `${sign}${(absVal / 1e6).toFixed(1)}M ₫`;
    if (absVal >= 1e3) return `${sign}${(absVal / 1e3).toFixed(0)}k ₫`;
    return `${sign}${absVal.toLocaleString('vi-VN')} ₫`;
  }

  if (absVal >= 1e6) return `${sign}${sym}${(absVal / 1e6).toFixed(1)}M`;
  if (absVal >= 1e3) return `${sign}${sym}${(absVal / 1e3).toFixed(1)}k`;
  return `${sign}${sym}${absVal.toFixed(0)}`;
}
