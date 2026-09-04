/**
 * FinScope Global State Manager
 */

import { api } from './api.js';

const now = new Date();
const currentYear = now.getFullYear();
const currentMonthNum = String(now.getMonth() + 1).padStart(2, '0');
const defaultMonth = `${currentYear}-${currentMonthNum}`;

export const state = {
  month: localStorage.getItem('finscope_month') || defaultMonth,
  accountId: null,
  privacyMode: localStorage.getItem('finscope_privacy') === 'true',
  accounts: [],
  categories: [],
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

  togglePrivacyMode() {
    this.privacyMode = !this.privacyMode;
    localStorage.setItem('finscope_privacy', this.privacyMode);
    document.body.classList.toggle('privacy-active', this.privacyMode);
    this.notify({ type: 'privacy_toggled', privacyMode: this.privacyMode });
  },

  async loadInitialData() {
    try {
      const [accs, cats] = await Promise.all([
        api.getAccounts(),
        api.getCategories()
      ]);
      this.accounts = accs;
      this.categories = cats;
      this.notify({ type: 'meta_loaded' });
    } catch (err) {
      console.error('Failed to load initial metadata:', err);
    }
  },

  formatCurrency(amount, forceMask = false) {
    if (this.privacyMode || forceMask) {
      return '••••••';
    }
    const val = Number(amount || 0);
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(val);
  },

  formatMonthLabel(monthStr) {
    if (!monthStr) return '';
    const [y, m] = monthStr.split('-');
    const date = new Date(Number(y), Number(m) - 1, 1);
    return date.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  }
};
