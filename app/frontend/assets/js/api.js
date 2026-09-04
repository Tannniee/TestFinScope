/**
 * FinScope API Client Bridge
 * Seamlessly talks to either PyWebView native API or local HTTP server.
 */

export const api = {
  async call(method, params = {}) {
    // If PyWebView native bridge is available
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[method] === 'function') {
      try {
        return await window.pywebview.api[method](params);
      } catch (err) {
        console.error(`PyWebView API error on ${method}:`, err);
        throw err;
      }
    }

    // Otherwise fallback to HTTP server
    try {
      const response = await fetch(`/api/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      });
      const data = await response.json();
      if (!data.success) {
        throw new Error(data.error || 'Unknown server error');
      }
      return data.data;
    } catch (err) {
      console.error(`HTTP API error on ${method}:`, err);
      throw err;
    }
  },

  // Accounts
  getAccounts(includeArchived = false) {
    return this.call('get_accounts', { include_archived: includeArchived });
  },

  // Categories
  getCategories(includeArchived = false, catType = null) {
    return this.call('get_categories', { include_archived: includeArchived, cat_type: catType });
  },

  // Transactions
  getTransactions(params = {}) {
    return this.call('get_transactions', params);
  },
  getTransaction(id) {
    return this.call('get_transaction', { tx_id: id });
  },
  createTransaction(data) {
    return this.call('create_transaction', { data });
  },
  updateTransaction(id, data) {
    return this.call('update_transaction', { tx_id: id, data });
  },
  deleteTransaction(id) {
    return this.call('delete_transaction', { tx_id: id });
  },
  duplicateTransaction(id) {
    return this.call('duplicate_transaction', { tx_id: id });
  },

  // Analytics & BI
  getMonthSummary(month, accountId = null) {
    return this.call('get_month_summary', { month, account_id: accountId });
  },
  getCalendarData(month, accountId = null) {
    return this.call('get_calendar_data', { month, account_id: accountId });
  },
  getAnalyticsDeepDive(month, accountId = null) {
    return this.call('get_analytics_deep_dive', { month, account_id: accountId });
  },

  // Budgets
  getMonthlyBudget(month) {
    return this.call('get_monthly_budget', { month });
  },
  setCategoryBudget(categoryId, month, amount) {
    return this.call('set_category_budget', { category_id: categoryId, month, amount });
  },

  // Backups & Health
  createBackup() {
    return this.call('create_backup');
  },
  listBackups() {
    return this.call('list_backups');
  },
  restoreBackup(filepath) {
    return this.call('restore_backup', { filepath });
  },
  getStorageHealth() {
    return this.call('get_storage_health');
  },
  seedDemoData(clearExisting = false) {
    return this.call('seed_demo_data', { clear_existing: clearExisting });
  }
};
