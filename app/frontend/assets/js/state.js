/**
 * FinScope Global State Manager
 * Dynamic currency, locale formatting, and state synchronization
 */

import { api } from './api.js';

const now = new Date();
const currentYear = now.getFullYear();
const currentMonthNum = String(now.getMonth() + 1).padStart(2, '0');
const defaultMonth = `${currentYear}-${currentMonthNum}`;

export const state = {
  month: localStorage.getItem('finscope_month') || defaultMonth,
  accountId: null,
  currency: 'USD',
  privacyMode: localStorage.getItem('finscope_privacy') === 'true',
  accounts: [],
  categories: [],
  settings: {},
  listeners: new Set(),

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  },

  notify(event) {
    this.listeners.forEach(fn => fn(event));
  },

  setMonth(newMonth) {
    this.month = newMonth;
    localStorage.setItem('finscope_month', newMonth);
    this.notify({ type: 'month_changed', month: newMonth });
  },

  prevMonth() {
    const [y, m] = this.month.split('-').map(Number);
    let prevY = y;
    let prevM = m - 1;
    if (prevM < 1) {
      prevM = 12;
      prevY -= 1;
    }
    this.setMonth(`${prevY}-${String(prevM).padStart(2, '0')}`);
  },

  nextMonth() {
    const [y, m] = this.month.split('-').map(Number);
    let nextY = y;
    let nextM = m + 1;
    if (nextM > 12) {
      nextM = 1;
      nextY += 1;
    }
    this.setMonth(`${nextY}-${String(nextM).padStart(2, '0')}`);
  },

  setAccountId(accId) {
    this.accountId = accId ? Number(accId) : null;
    this.notify({ type: 'account_changed', accountId: this.accountId });
  },

  async setCurrency(currencyCode) {
    await api.updateSettings({ currency: currencyCode });
    this.currency = currencyCode;
    this.notify({ type: 'currency_changed', currency: currencyCode });
  },

  togglePrivacyMode() {
    this.privacyMode = !this.privacyMode;
    localStorage.setItem('finscope_privacy', this.privacyMode);
    document.body.classList.toggle('privacy-active', this.privacyMode);
    this.notify({ type: 'privacy_toggled', privacyMode: this.privacyMode });
  },

  async reloadMetadata({ notify = true, retries = 2 } = {}) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const [accs, cats, settings] = await Promise.all([
          api.getAccounts(),
          api.getCategories(),
          api.getSettings()
        ]);
        this.accounts = accs;
        this.categories = cats;
        this.settings = settings || {};
        if (this.settings.currency) {
          this.currency = this.settings.currency;
        }
        if (notify) {
          this.notify({ type: 'meta_loaded' });
        }
        return;
      } catch (err) {
        if (attempt === retries) {
          console.error('Failed to reload metadata after retries:', err);
          this.notify({ type: 'meta_load_error', error: err });
          throw err;
        }
        await new Promise(r => setTimeout(r, 300 * (attempt + 1)));
      }
    }
  },

  async loadInitialData() {
    try {
      await this.reloadMetadata({ notify: true });
    } catch (err) {
      console.error('Initial data bootstrap failed:', err);
    }
  },

  formatCurrency(amount, currency = null, forceMask = false) {
    if (this.privacyMode || (typeof currency === 'boolean' && currency) || forceMask) {
      return '••••••';
    }
    const val = Number(amount || 0);
    const curr = (typeof currency === 'string' && currency) ? currency : (this.currency || 'USD');

    try {
      const locale = curr === 'VND' ? 'vi-VN' : 'en-US';
      const fractionDigits = (curr === 'VND' || curr === 'JPY' || curr === 'KRW') ? 0 : (curr === 'KWD' || curr === 'BHD' ? 3 : 2);

      return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: curr,
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits
      }).format(val);
    } catch (err) {
      return `${curr} ${val.toFixed(2)}`;
    }
  },

  formatMonthLabel(monthStr) {
    if (!monthStr) return '';
    const [y, m] = monthStr.split('-');
    const date = new Date(Number(y), Number(m) - 1, 1);
    return date.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  }
};
