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
    this.currency = currencyCode;
    try {
      await api.updateSettings({ currency: currencyCode });
      this.notify({ type: 'currency_changed', currency: currencyCode });
    } catch (err) {
      console.error('Failed to update currency setting:', err);
    }
  },

  togglePrivacyMode() {
    this.privacyMode = !this.privacyMode;
    localStorage.setItem('finscope_privacy', this.privacyMode);
    document.body.classList.toggle('privacy-active', this.privacyMode);
    this.notify({ type: 'privacy_toggled', privacyMode: this.privacyMode });
  },

  async reloadMetadata({ notify = true } = {}) {
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
    } catch (err) {
      console.error('Failed to reload metadata:', err);
    }
  },

  async loadInitialData() {
    await this.reloadMetadata({ notify: true });
  },

  formatCurrency(amount, forceMask = false) {
    if (this.privacyMode || forceMask) {
      return '••••••';
    }
    const val = Number(amount || 0);
    const curr = this.currency || 'USD';

    try {
      const locale = curr === 'VND' ? 'vi-VN' : 'en-US';
      const fractionDigits = curr === 'VND' || curr === 'JPY' ? 0 : 2;

      return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: curr,
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits
      }).format(val);
    } catch (err) {
      return `$${val.toFixed(2)}`;
    }
  },

  formatMonthLabel(monthStr) {
    if (!monthStr) return '';
    const [y, m] = monthStr.split('-');
    const date = new Date(Number(y), Number(m) - 1, 1);
    return date.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  }
};
