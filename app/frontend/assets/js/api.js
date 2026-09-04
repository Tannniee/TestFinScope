/**
 * FinScope API Client Bridge
 * Single unified HTTP business transport with session security.
 */

export const api = {
  _sessionToken: null,

  async getSessionToken() {
    if (window.__FINSCOPE_TOKEN__) {
      return window.__FINSCOPE_TOKEN__;
    }
    if (this._sessionToken) {
      return this._sessionToken;
    }
    try {
      const resp = await fetch('/api/bootstrap');
      const payload = await resp.json();
      if (payload && payload.success && payload.data && payload.data.token) {
        this._sessionToken = payload.data.token;
        window.__FINSCOPE_TOKEN__ = this._sessionToken;
        return this._sessionToken;
      }
    } catch (e) {
      console.warn('Could not bootstrap session token:', e);
    }
    return '';
  },

  async call(method, params = {}, options = {}) {
    const token = await this.getSessionToken();
    try {
      const fetchOpts = {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-FinScope-Token': token
        },
        body: JSON.stringify(params)
      };
      if (options.signal) {
        fetchOpts.signal = options.signal;
      }
      const response = await fetch(`/api/${method}`, fetchOpts);
      const data = await response.json();
      if (!data.success) {
        const errorMsg = (data.error && data.error.message) || (typeof data.error === 'string' ? data.error : 'Unknown server error');
        throw new Error(errorMsg);
      }
      return data.data;
    } catch (err) {
      if (err.name === 'AbortError') {
        throw err;
      }
      console.error(`API error on ${method}:`, err);
      throw err;
    }
  },

  // Accounts
  getAccounts(includeArchived = false) {
    return this.call('get_accounts', { include_archived: includeArchived });
  },
  createAccount(data) {
    return this.call('create_account', data);
  },
  updateAccount(id, data) {
    return this.call('update_account', { account_id: id, ...data });
  },
  deleteAccount(id) {
    return this.call('delete_account', { account_id: id });
  },

  // Categories
  getCategories(includeArchived = false, catType = null) {
    return this.call('get_categories', { include_archived: includeArchived, cat_type: catType });
  },
  createCategory(data) {
    return this.call('create_category', data);
  },
  updateCategory(id, data) {
    return this.call('update_category', { category_id: id, ...data });
  },
  deleteCategory(id) {
    return this.call('delete_category', { category_id: id });
  },

  // Transactions
  getTransactions(params = {}, options = {}) {
    return this.call('get_transactions', params, options);
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
  updateTransfer(params) {
    return this.call('update_transfer', params);
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
  updateRefund(params) {
    return this.call('update_refund', params);
  },
  undoDeleteTransaction(id) {
    return this.call('undo_delete_transaction', { tx_id: id });
  },
  duplicateTransaction(id) {
    return this.call('duplicate_transaction', { tx_id: id });
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
  getMonthlyBudget(month, accountId = null) {
    return this.call('get_monthly_budget', { month, account_id: accountId });
  },
  setCategoryBudget(categoryId, month, amount) {
    return this.call('set_category_budget', { category_id: categoryId, month, amount });
  },

  // Bank CSV Import Wizard
  previewCsvImport(csvContent, mapping = {}, accountId = null) {
    return this.call('preview_csv_import', { csv_content: csvContent, mapping, account_id: accountId });
  },
  commitCsvImport(csvContent, mapping = {}, accountId = null, deduplicate = true) {
    return this.call('commit_csv_import', { csv_content: csvContent, mapping, account_id: accountId, deduplicate });
  },

  // Recurring Rules & Bills
  getRecurringRules(accountId = null, activeOnly = false) {
    return this.call('get_recurring_rules', { account_id: accountId, active_only: activeOnly });
  },
  createRecurringRule(data) {
    return this.call('create_recurring_rule', data);
  },
  updateRecurringRule(ruleId, data) {
    return this.call('update_recurring_rule', { rule_id: ruleId, ...data });
  },
  deleteRecurringRule(ruleId) {
    return this.call('delete_recurring_rule', { rule_id: ruleId });
  },
  getUpcomingBills(month, accountId = null) {
    return this.call('get_upcoming_bills', { month, account_id: accountId });
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
