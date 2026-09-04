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

const routes = {
  '#overview': { title: 'Overview Dashboard', subtitle: 'Personal financial snapshot & core metrics', render: renderOverviewPage },
  '#transactions': { title: 'Transactions', subtitle: 'Search, filter, and manage records', render: renderTransactionsPage },
  '#calendar': { title: 'Calendar Matrix', subtitle: 'Daily spending intensity & cash flow timeline', render: renderCalendarPage },
  '#analytics': { title: 'BI Analytics', subtitle: 'Variance explanation, pacing curves & patterns', render: renderAnalyticsPage },
  '#budget': { title: 'Budget System', subtitle: 'Category limits, pacing, and month-end projections', render: renderBudgetPage },
  '#reports': { title: 'Financial Reports', subtitle: 'Formal monthly & annual statement generation', render: renderReportsPage },
  '#settings': { title: 'Data & Settings', subtitle: 'Local storage health, backup snapshots & demo data', render: renderSettingsPage },
};

export const router = {
  currentRoute: '#overview',

  init() {
    window.addEventListener('hashchange', () => this.handleNavigation());
    
    // Listen to global state changes that warrant a view refresh
    state.subscribe((event) => {
      if (['month_changed', 'account_changed', 'data_changed', 'privacy_toggled'].includes(event.type)) {
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

  renderCurrentView() {
    const container = document.getElementById('page-container');
    const route = routes[this.currentRoute];
    if (container && route) {
      route.render(container);
    }
  }
};
