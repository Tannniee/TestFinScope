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
  currencyCatalog: new Map(),
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

  getMinorUnit(currency = null) {
    const code = ((typeof currency === 'string' && currency) ? currency : (this.currency || 'USD')).toUpperCase();
    const info = this.currencyCatalog.get(code);
    if (info && typeof info.minor_unit === 'number') {
      return info.minor_unit;
    }
    if (code === 'VND' || code === 'JPY' || code === 'KRW' || code === 'CLP') return 0;
    if (code === 'BHD' || code === 'KWD' || code === 'OMR') return 3;
    return 2;
  },

  getAmountStep(currency = null) {
    const unit = this.getMinorUnit(currency);
    if (unit === 0) return '1';
    if (unit === 3) return '0.001';
    return '0.01';
  },

  async reloadMetadata({ notify = true, retries = 2 } = {}) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const [accs, cats, settings, catalog] = await Promise.all([
          api.getAccounts(),
          api.getCategories(),
          api.getSettings(),
          api.getCurrencyCatalog().catch(() => [])
        ]);
        this.accounts = accs;
        this.categories = cats;
        this.settings = settings || {};
        if (this.settings.currency) {
          this.currency = this.settings.currency;
        }
        if (Array.isArray(catalog)) {
          this.currencyCatalog.clear();
          catalog.forEach(c => {
            if (c && c.code) this.currencyCatalog.set(c.code.toUpperCase(), c);
          });
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
    const curr = (typeof currency === 'string' && currency) ? currency.toUpperCase() : (this.currency || 'USD').toUpperCase();

    try {
      const locale = curr === 'VND' ? 'vi-VN' : 'en-US';
      const fractionDigits = this.getMinorUnit(curr);

      return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: curr,
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits
      }).format(val);
    } catch (err) {
      const decimals = this.getMinorUnit(curr);
      return `${curr} ${val.toFixed(decimals)}`;
    }
  },

  formatMonthLabel(monthStr) {
    if (!monthStr) return '';
    const [y, m] = monthStr.split('-');
    const date = new Date(Number(y), Number(m) - 1, 1);
    return date.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  }
};
