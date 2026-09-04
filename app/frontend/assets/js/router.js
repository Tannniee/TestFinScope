/**
 * FinScope Client Router
 * Handles hash-based navigation between views
 */

import { state } from './state.js';
import { renderOverviewPage } from './pages/overview.js';
import { renderTransactionsPage } from './pages/transactions.js';
import { renderCalendarPage } from './pages/calendar.js';
import { renderAnalyticsPage } from './pages/analytics.js';
import { renderBudgetPage } from './pages/budget.js';
import { renderReportsPage } from './pages/reports.js';
import { renderSettingsPage } from './pages/settings.js';
import { renderImportPage } from './pages/import.js';

const routes = {
  '#overview': { title: 'Overview Dashboard', subtitle: 'Personal financial snapshot & core metrics', render: renderOverviewPage },
  '#transactions': { title: 'Transactions', subtitle: 'Search, filter, and manage records', render: renderTransactionsPage },
  '#calendar': { title: 'Calendar Matrix', subtitle: 'Daily spending intensity & cash flow timeline', render: renderCalendarPage },
  '#analytics': { title: 'BI Analytics', subtitle: 'Variance explanation, pacing curves & patterns', render: renderAnalyticsPage },
  '#budget': { title: 'Budget System', subtitle: 'Category limits, pacing, and month-end projections', render: renderBudgetPage },
  '#reports': { title: 'Financial Reports', subtitle: 'Formal monthly & annual statement generation', render: renderReportsPage },
  '#import': { title: 'Bank CSV Import', subtitle: '4-step wizard to upload, map columns, preview duplicates, and batch import', render: renderImportPage },
  '#settings': { title: 'Data & Settings', subtitle: 'Local storage health, backup snapshots & demo data', render: renderSettingsPage },
};

export const router = {
  currentRoute: '#overview',
  renderGeneration: 0,

  init() {
    window.addEventListener('hashchange', () => this.handleNavigation());
    
    // Listen to global state changes that warrant a view refresh
    state.subscribe((event) => {
      if (['month_changed', 'account_changed', 'data_changed', 'database_restored'].includes(event.type)) {
        this.renderCurrentView();
      }
    });

    this.handleNavigation();
  },

  handleNavigation() {
    const hash = window.location.hash || '#overview';
    this.currentRoute = routes[hash] ? hash : '#overview';

    // Update active nav class
    document.querySelectorAll('.nav-item').forEach(item => {
      const itemHash = item.getAttribute('href');
      item.classList.toggle('active', itemHash === this.currentRoute);
    });

    // Update topbar title & subtitle
    const pageInfo = routes[this.currentRoute];
    const titleEl = document.getElementById('page-title');
    const subtitleEl = document.getElementById('page-subtitle');
    if (titleEl) titleEl.textContent = pageInfo.title;
    if (subtitleEl) subtitleEl.textContent = pageInfo.subtitle;

    this.renderCurrentView();
  },

  async renderCurrentView() {
    const container = document.getElementById('page-container');
    const route = routes[this.currentRoute];
    if (!container || !route) return;

    // AUD-014: Increment generation token on every navigation or state refresh
    this.renderGeneration += 1;
    const generation = this.renderGeneration;

    try {
      await route.render(container);
    } catch (err) {
      if (generation !== this.renderGeneration) {
        // Rapid navigation occurred; ignore stale error
        return;
      }
      console.error('Render error:', err);
    }

    if (generation !== this.renderGeneration) {
      // Stale render from previous route navigation, discard
      return;
    }
  }
};
