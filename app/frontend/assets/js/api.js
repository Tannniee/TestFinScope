/**
 * FinScope API Client Bridge
 * Seamlessly talks to either PyWebView native API or local HTTP server.
 */

export const api = {
  async call(method, params = {}) {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[method] === 'function') {
      try {
        return await window.pywebview.api[method](params);
      } catch (err) {
        console.error(`PyWebView API error on ${method}:`, err);
        throw err;
      }
    }

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
  createTransfer(params) {
    return this.call('create_transfer', params);
  },
  updateTransaction(id, data) {
    return this.call('update_transaction', { tx_id: id, data });
  },
  deleteTransaction(id) {
    return this.call('delete_transaction', { tx_id: id });
  },
  createRefund(params) {
    return this.call('create_refund', params);
  },
  undoDeleteTransaction(id) {
    return this.call('undo_delete_transaction', { tx_id: id });
  },
  getMerchantSuggestions(query, limit = 6) {
    return this.call('get_merchant_suggestions', { query, limit });
  },
  getRecentPayees(limit = 5) {
    return this.call('get_recent_payees', { limit });
  },
  getReviewQueue(limit = 50, offset = 0) {
    return this.call('get_review_queue', { limit, offset });
  },
  resolveReview(txId, categoryId, merchantName = null) {
    return this.call('resolve_review', { tx_id: txId, category_id: categoryId, merchant_name: merchantName });
  },

  // Analytics & BI V2
  getAnalyticsContext(month = null, accountId = null, categoryId = null, merchantId = null, comparisonMode = null) {
    return this.call('get_analytics_context', {
      month,
      account_id: accountId,
      category_id: categoryId,
      merchant_id: merchantId,
      comparison_mode: comparisonMode
    });
  },
  getMonthSummary(month, accountId = null) {
    return this.call('get_month_summary', { month, account_id: accountId });
  },
  getCalendarData(month, accountId = null) {
    return this.call('get_calendar_data', { month, account_id: accountId });
  },
  getAnalyticsDeepDive(month, accountId = null) {
    return this.call('get_analytics_deep_dive', { month, account_id: accountId });
  },
  getRollingMetrics(metric = 'expense', categoryId = null, accountId = null, asOfMonth = null) {
    return this.call('get_rolling_metrics', { metric, category_id: categoryId, account_id: accountId, as_of_month: asOfMonth });
  },
  getWhatChanged(currentMonth, comparisonMonth = null, accountId = null, maxDay = null, comparisonMode = null) {
    return this.call('get_what_changed', {
      current_month: currentMonth,
      comparison_month: comparisonMonth,
      account_id: accountId,
      max_day: maxDay,
      comparison_mode: comparisonMode
    });
  },
  getMerchantDrilldown(categoryId, currentMonth = null, accountId = null, comparisonMode = null) {
    return this.call('get_merchant_drilldown', {
      category_id: categoryId,
      current_month: currentMonth,
      account_id: accountId,
      comparison_mode: comparisonMode
    });
  },
  getSpendingFingerprint(monthsWindow = 6, accountId = null, asOfMonth = null) {
    return this.call('get_spending_fingerprint', { months_window: monthsWindow, account_id: accountId, as_of_month: asOfMonth });
  },
  getAnomalies(month, accountId = null, kRange = 2.5) {
    return this.call('get_anomalies', { month, account_id: accountId, k_range: kRange });
  },
  getNormalRanges(accountId = null, asOfDate = null) {
    return this.call('get_normal_ranges', { account_id: accountId, as_of_date: asOfDate });
  },
  getForecast(month, accountId = null, asOfDate = null) {
    return this.call('get_forecast', { month, account_id: accountId, as_of_date: asOfDate });
  },
  getRankedInsights(month, accountId = null, limit = 5) {
    return this.call('get_ranked_insights', { month, account_id: accountId, limit });
  },
  dismissInsight(insightKey) {
    return this.call('dismiss_insight', { insight_key: insightKey });
  },
  getBacktestEvaluation(accountId = null) {
    return this.call('get_backtest_evaluation', { account_id: accountId });
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
  },
  openDataDir() {
    return this.call('open_data_dir');
  },

  // Settings
  getSettings() {
    return this.call('get_settings');
  },
  updateSettings(settings) {
    return this.call('update_settings', { settings });
  }
};
