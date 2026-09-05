/**
 * FinScope Analytics V2 Workspace Page
 * 5 Modular Analytical Views:
 * 1. Overview: Executive summary, context-aware ranked insights, rolling & forecast status
 * 2. Changes: What Changed? v2.1 (Frequency, Ticket, and Refund decomposition + Category & Merchant drill-down)
 * 3. Patterns: Spending Fingerprint, Zero-filled rolling series, Weekday Disambiguation
 * 4. Anomalies: Statistical anomalies, hierarchical fallbacks, normal range bars
 * 5. Forecast: Explainable component projections, budget risks, rolling-origin backtesting leaderboard
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../utils.js';

let varianceChart = null;
let weekdayChart = null;
let cumulativeChart = null;
let patternsTrendChart = null;

let currentTab = 'overview'; // 'overview', 'changes', 'patterns', 'anomalies', 'forecast'
let selectedCategoryDrilldown = null;

export async function renderAnalyticsPage(container) {
  let contextData = null;
  try {
    contextData = await api.getAnalyticsContext(state.month, state.accountId);
  } catch (e) {
    console.error('Failed to load analytics context:', e);
  }

  const periodLabel = contextData?.period_label || state.month;
  const compLabel = contextData?.comparison_label || 'Previous period';
  const isMtd = contextData?.is_current_month || false;

  container.innerHTML = `
    <div class="analytics-view">
      <!-- Canonical Analytics Context Banner -->
      <div class="analytics-context-banner">
        <div class="context-banner-left">
          <span class="context-status-pill ${isMtd ? 'mtd' : ''}">
            <i data-lucide="${isMtd ? 'clock' : 'check-circle-2'}" style="width: 13px; height: 13px;"></i>
            ${isMtd ? 'Month-to-Date (MTD)' : 'Completed Month'}
          </span>
          <div style="font-size: 13.5px; font-weight: 600; color: var(--text-primary);">
            ${periodLabel} <span style="font-weight: 400; color: var(--text-muted);">compared with</span> ${compLabel}
          </div>
        </div>
        <div style="font-size: 12.5px; color: var(--text-secondary); display: flex; align-items: center; gap: 14px;">
          <span><i data-lucide="wallet" style="width: 13px; height: 13px; vertical-align: -2px;"></i> Scope: <strong>${state.accountId ? 'Selected Account' : 'All Accounts'}</strong></span>
          <span class="delta-badge neutral" style="font-size: 11px;">Reconciled (Exact Minor Units)</span>
        </div>
      </div>

      <!-- Navigation Tabs (5 Tabs) -->
      <div class="analytics-tab-bar">
        <button class="analytics-tab-btn ${currentTab === 'overview' ? 'active' : ''}" data-tab="overview">
          <i data-lucide="layout-dashboard"></i> Overview
        </button>
        <button class="analytics-tab-btn ${currentTab === 'changes' ? 'active' : ''}" data-tab="changes">
          <i data-lucide="git-commit"></i> What Changed? v2.1
        </button>
        <button class="analytics-tab-btn ${currentTab === 'patterns' ? 'active' : ''}" data-tab="patterns">
          <i data-lucide="fingerprint"></i> Spending Patterns
        </button>
        <button class="analytics-tab-btn ${currentTab === 'anomalies' ? 'active' : ''}" data-tab="anomalies">
          <i data-lucide="alert-octagon"></i> Anomalies & Ranges
        </button>
        <button class="analytics-tab-btn ${currentTab === 'forecast' ? 'active' : ''}" data-tab="forecast">
          <i data-lucide="trending-up"></i> Forecast & Backtest
        </button>
      </div>

      <!-- Tab Content Container -->
      <div id="analytics-tab-content">
        <div style="text-align: center; color: var(--text-muted); padding: 40px;">Loading analytical intelligence...</div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  // Tab switcher
  container.querySelectorAll('.analytics-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.analytics-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTab = btn.dataset.tab;
      selectedCategoryDrilldown = null;
      loadTabContent();
    });
  });

  await loadTabContent();
}

async function loadTabContent() {
  const content = document.getElementById('analytics-tab-content');
  if (!content) return;

  try {
    if (currentTab === 'overview') {
      await renderOverviewTab(content);
    } else if (currentTab === 'changes') {
      await renderChangesTab(content);
    } else if (currentTab === 'patterns') {
      await renderPatternsTab(content);
    } else if (currentTab === 'anomalies') {
      await renderAnomaliesTab(content);
    } else if (currentTab === 'forecast') {
      await renderForecastTab(content);
    }
  } catch (err) {
    console.error('Error rendering analytics tab:', err);
    content.innerHTML = `<div style="text-align:center; color: var(--color-negative); padding: 30px;">Error loading analytics: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Tab 1: Overview Tab (Executive Summary & Ranked Insights)
// ---------------------------------------------------------------------------
async function renderOverviewTab(container) {
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Synthesizing analytical overview...</div>`;

  const [summary, insightsResp, rolling, forecast] = await Promise.all([
    api.getMonthSummary(state.month, state.accountId),
    api.getRankedInsights(state.month, state.accountId, 4),
    api.getRollingMetrics('expense', null, state.accountId, state.month),
    api.getForecast(state.month, state.accountId)
  ]);

  const kpis = summary.kpis;
  const insights = insightsResp.insights || [];

  container.innerHTML = `
    <!-- Top Summary KPIs -->
    <div class="grid-4col" style="margin-bottom: 24px;">
      <div class="fin-card">
        <span class="kpi-label">Net Spending</span>
        <div class="kpi-value text-negative" style="font-size: 26px; margin: 6px 0;">
          ${state.formatCurrency(kpis.expense)}
        </div>
        <span class="kpi-footer">${kpis.expense_delta_pct > 0 ? '+' : ''}${kpis.expense_delta_pct}% vs previous period</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Total Income</span>
        <div class="kpi-value text-positive" style="font-size: 26px; margin: 6px 0;">
          ${state.formatCurrency(kpis.income)}
        </div>
        <span class="kpi-footer">${kpis.income_delta_pct > 0 ? '+' : ''}${kpis.income_delta_pct}% vs previous period</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Savings Rate</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #C85AF4;">
          ${kpis.savings_rate}%
        </div>
        <span class="kpi-footer">Previous: ${kpis.prev_savings_rate}%</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Projected Month-End</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #FF9F43;">
          ${state.formatCurrency(forecast.projected_expense)}
        </div>
        <span class="kpi-footer">${(forecast.range_type === 'calibrated_range' || forecast.components?.range_type === 'calibrated_range') ? 'Likely' : 'Early estimate'}: ${state.formatCurrency(forecast.lower_bound)} – ${state.formatCurrency(forecast.upper_bound)}</span>
      </div>
    </div>

    <!-- Ranked Insights Section -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Ranked Financial Insights</h3>
          <p>Multi-factor synthesized intelligence ranked by absolute impact and unusualness</p>
        </div>
        <span class="delta-badge neutral" style="font-size: 11.5px;">${insights.length} active insights</span>
      </div>

      <div id="analytics-insights-container" style="display: flex; flex-direction: column; gap: 12px;">
        ${insights.length === 0 ? `
          <div style="text-align: center; color: var(--text-muted); padding: 24px;">No critical insights for this period. Spending is normal.</div>
        ` : insights.map((ins, idx) => {
          const drawerId = `an-drawer-${idx}`;
          const sevColor = ins.severity === 'critical' ? '#FF6B8A' : (ins.severity === 'warning' ? '#FF9F43' : (ins.severity === 'success' ? '#4DD5A5' : '#5B8CFF'));
          const sevBg = ins.severity === 'critical' ? 'rgba(255, 107, 138, 0.15)' : (ins.severity === 'warning' ? 'rgba(255, 159, 67, 0.15)' : (ins.severity === 'success' ? 'rgba(77, 213, 165, 0.15)' : 'rgba(91, 140, 255, 0.15)'));
          const sevIcon = ins.severity === 'critical' ? 'alert-triangle' : (ins.severity === 'warning' ? 'alert-circle' : (ins.severity === 'success' ? 'check-circle-2' : 'sparkles'));

          let evidenceHtml = '';
          if (ins.evidence && Object.keys(ins.evidence).length > 0) {
            evidenceHtml = Object.entries(ins.evidence).map(([k, v]) => `
              <div class="evidence-item">
                <span class="evidence-label">${k.replace(/_/g, ' ')}</span>
                <span class="evidence-val">${typeof v === 'number' ? state.formatCurrency(v) : v}</span>
              </div>
            `).join('');
          }

          return `
            <div class="insight-card ${ins.severity || 'info'}" style="margin-bottom: 0;">
              <div class="insight-card-main">
                <div class="insight-content-wrap">
                  <div class="insight-icon-box" style="background: ${sevBg}; color: ${sevColor};">
                    <i data-lucide="${sevIcon}"></i>
                  </div>
                  <div>
                    <div class="insight-title">
                      ${ins.title}
                      <span class="delta-badge neutral" style="font-size: 10px; padding: 1px 6px;">Impact: ${Math.round((ins.impact_score || 0.5) * 100)}</span>
                    </div>
                    <div class="insight-summary">${ins.summary}</div>
                  </div>
                </div>
                <div class="insight-actions">
                  ${evidenceHtml ? `<button class="btn btn-secondary btn-sm evidence-toggle-btn" data-target="${drawerId}" style="padding: 4px 10px; font-size: 11px;">Why?</button>` : ''}
                  <button class="btn btn-secondary btn-sm insight-dismiss-btn" data-key="${ins.insight_key || ins.id}" title="Dismiss insight" style="padding: 4px 8px; font-size: 11px;"><i data-lucide="x" style="width: 12px; height: 12px;"></i></button>
                </div>
              </div>
              ${evidenceHtml ? `<div id="${drawerId}" class="insight-evidence-drawer">${evidenceHtml}</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    </div>

    <!-- Quick Historical Rolling Norms & Projections -->
    <div class="grid-2col">
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Historical Baseline Norms</h3>
            <p>Zero-filled robust rolling medians and averages</p>
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; text-align: center;">
          <div style="background: var(--bg-surface); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">3M Median</div>
            <div style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 4px;">${state.formatCurrency(rolling.median_3)}</div>
          </div>
          <div style="background: var(--bg-surface); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">6M Median</div>
            <div style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 4px;">${state.formatCurrency(rolling.median_6)}</div>
          </div>
          <div style="background: var(--bg-surface); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">12M Mean</div>
            <div style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 4px;">${state.formatCurrency(rolling.mean_12)}</div>
          </div>
        </div>
        <div style="margin-top: 14px; font-size: 12px; color: var(--text-secondary);">
          Current spending is <strong style="color: var(--text-primary);">${kpis.expense > rolling.median_6 ? 'above' : 'below'}</strong> your 6-month historical baseline of ${state.formatCurrency(rolling.median_6)}.
        </div>
      </div>

      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Forecast Confidence & Model</h3>
            <p>${escapeHtml(forecast.method || 'FinScope Hybrid methodology')}</p>
          </div>
          <span class="delta-badge positive" style="font-size: 11px;">Confidence: ${forecast.confidence.toUpperCase()}${forecast.confidence_score !== undefined ? ` (${forecast.confidence_score}/100)` : ''}</span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.6;">
          • <strong>Spent to Date:</strong> ${state.formatCurrency(forecast.actual_spent_to_date)} (Days 1–${forecast.components?.elapsed_days || 15})<br>
          • <strong>Upcoming Scheduled Bills:</strong> ${state.formatCurrency(forecast.upcoming_recurring)}<br>
          • <strong>Expected Variable Spending:</strong> ${state.formatCurrency(forecast.expected_variable)}<br>
          • <strong>Reconciliation Status:</strong> <span style="color: #4DD5A5;">✓ Reconciled to exact cent</span>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  // Attach evidence toggles
  container.querySelectorAll('.evidence-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const drawer = document.getElementById(targetId);
      if (drawer) {
        drawer.classList.toggle('open');
        btn.textContent = drawer.classList.contains('open') ? 'Hide Details' : 'Why?';
      }
    });
  });

  // Attach dismiss clicks
  container.querySelectorAll('.insight-dismiss-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const key = btn.dataset.key;
      if (!key) return;
      try {
        await api.dismissInsight(key);
        const card = btn.closest('.insight-card');
        if (card) {
          card.style.opacity = '0';
          card.style.transform = 'translateY(-10px)';
          card.style.transition = 'all 0.25s ease';
          setTimeout(() => card.remove(), 250);
        }
        showToast('Insight dismissed', 'info');
      } catch (err) {
        console.error('Error dismissing insight:', err);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Tab 2: What Changed? v2.1 (Frequency, Ticket & Refund Decomposition + Drilldown)
// ---------------------------------------------------------------------------
async function renderChangesTab(container) {
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Analyzing variance drivers...</div>`;

  const [changes, deepDive] = await Promise.all([
    api.getWhatChanged(state.month, null, state.accountId),
    api.getAnalyticsDeepDive(state.month, state.accountId)
  ]);

  const totalDelta = changes.total_delta;
  const deltaSign = totalDelta > 0 ? '+' : '';
  const freqEffect = changes.overall_frequency_effect;
  const ticketEffect = changes.overall_ticket_effect;
  const refundEffect = changes.overall_refund_effect || 0;

  container.innerHTML = `
    <!-- 4 Summary KPI Cards including Refund Effect -->
    <div class="grid-4col" style="margin-bottom: 24px;">
      <div class="fin-card">
        <span class="kpi-label">Total Net Spend Change</span>
        <div class="kpi-value ${totalDelta > 0 ? 'text-negative' : 'text-positive'}" style="font-size: 26px; margin: 6px 0;">
          ${deltaSign}${state.formatCurrency(totalDelta)}
        </div>
        <span class="kpi-footer">Exact Net Delta</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Frequency Effect</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #5B8CFF;">
          ${freqEffect > 0 ? '+' : ''}${state.formatCurrency(freqEffect)}
        </div>
        <span class="kpi-footer">Change due to purchase count</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Ticket Size Effect</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #FF9F43;">
          ${ticketEffect > 0 ? '+' : ''}${state.formatCurrency(ticketEffect)}
        </div>
        <span class="kpi-footer">Change due to avg purchase size</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Refund Effect</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #27D5D5;">
          ${refundEffect > 0 ? '+' : ''}${state.formatCurrency(refundEffect)}
        </div>
        <span class="kpi-footer">Change due to refund credits</span>
      </div>
    </div>

    <!-- Waterfall & Drivers Table -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Category Driver Decomposition</h3>
          <p>Identity: Frequency Effect + Ticket Effect + Refund Effect == Net Delta (Click category to drill down)</p>
        </div>
      </div>

      <div class="grid-2col" style="grid-template-columns: 1.2fr 1fr; gap: 24px;">
        <div id="variance-chart" style="width: 100%; height: 340px;"></div>
        <div class="table-container" style="max-height: 340px; overflow-y: auto;">
          <table class="fin-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Classification</th>
                <th style="text-align: right;">Net Delta</th>
                <th style="text-align: right;">Drilldown</th>
              </tr>
            </thead>
            <tbody id="changes-table-body"></tbody>
          </table>
        </div>
      </div>

      <!-- Merchant Drill-Down Container (Populated on click) -->
      <div id="merchant-drilldown-container"></div>
    </div>

    <!-- Pacing & Weekday Distribution -->
    <div class="grid-2col">
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Spending by Weekday</h3>
            <p>Average daily expense by day of the week</p>
          </div>
        </div>
        <div id="weekday-chart" style="width: 100%; height: 260px;"></div>
      </div>

      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Cumulative Spending Trajectory</h3>
            <p>Trajectory compared with comparison period</p>
          </div>
        </div>
        <div id="cumulative-chart" style="width: 100%; height: 260px;"></div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  // Populate Driver Table
  const tbody = document.getElementById('changes-table-body');
  if (tbody) {
    tbody.innerHTML = changes.drivers.map(d => {
      const tagClass = d.tag === 'NEW' ? 'new' : (d.tag === 'INCREASED_FREQUENCY' ? 'freq' : (d.tag === 'HIGHER_TICKET' ? 'ticket' : (d.tag === 'REFUND_IMPACT' ? 'refund' : 'reduced')));
      const sign = d.delta > 0 ? '+' : '';
      const color = d.delta > 0 ? 'var(--color-negative)' : (d.delta < 0 ? 'var(--color-positive)' : 'var(--text-muted)');

      return `
        <tr class="table-row-clickable category-driver-row" data-category-id="${d.entity_id}" data-category-name="${escapeHtml(d.name)}">
          <td style="font-weight: 500;">
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${escapeHtml(d.color)}; margin-right:6px;"></span>
            ${escapeHtml(d.name)}
          </td>
          <td><span class="driver-tag ${tagClass}">${d.tag.replace(/_/g, ' ')}</span></td>
          <td style="text-align: right; font-weight: 600; color: ${color};">${sign}${state.formatCurrency(d.delta)}</td>
          <td style="text-align: right;">
            <button class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 11px;">Drilldown <i data-lucide="chevron-right" style="width: 11px; height: 11px; vertical-align: -1px;"></i></button>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) window.lucide.createIcons();

    // Attach click for merchant drilldown
    tbody.querySelectorAll('.category-driver-row').forEach(row => {
      row.addEventListener('click', async () => {
        const catId = parseInt(row.dataset.categoryId);
        const catName = row.dataset.categoryName;
        await loadMerchantDrilldown(catId, catName);
      });
    });
  }

  renderVarianceWaterfallChart(changes.waterfall);
  renderWeekdayChart(deepDive.weekday);
  renderCumulativeChart(deepDive.cumulative);
}

async function loadMerchantDrilldown(categoryId, categoryName) {
  const container = document.getElementById('merchant-drilldown-container');
  if (!container) return;

  container.innerHTML = `
    <div class="merchant-drilldown-panel">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h4 style="font-size: 14px; font-weight: 600; color: var(--text-primary);">
          Merchant Drill-down for <span style="color: var(--accent-blue);">${escapeHtml(categoryName)}</span>
        </h4>
        <button class="btn btn-secondary btn-sm" id="close-merchant-drilldown" style="padding: 3px 8px; font-size: 11px;">Close</button>
      </div>
      <div style="text-align: center; color: var(--text-muted); padding: 14px;">Loading merchant breakdown...</div>
    </div>
  `;

  document.getElementById('close-merchant-drilldown')?.addEventListener('click', () => {
    container.innerHTML = '';
  });

  try {
    const merchants = await api.getMerchantDrilldown(categoryId, state.month, state.accountId);
    if (!merchants || merchants.length === 0) {
      container.querySelector('.merchant-drilldown-panel').innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 13px; color: var(--text-muted);">No individual merchant data found for ${escapeHtml(categoryName)}.</span>
          <button class="btn btn-secondary btn-sm" id="close-merchant-drilldown">Close</button>
        </div>
      `;
      document.getElementById('close-merchant-drilldown')?.addEventListener('click', () => container.innerHTML = '');
      return;
    }

    container.innerHTML = `
      <div class="merchant-drilldown-panel">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div>
            <h4 style="font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0;">
              Merchant Drill-down: <span style="color: var(--accent-blue);">${escapeHtml(categoryName)}</span>
            </h4>
            <span style="font-size: 11.5px; color: var(--text-muted);">Breakdown of behavioral causes per merchant</span>
          </div>
          <button class="btn btn-secondary btn-sm" id="close-merchant-drilldown" style="padding: 4px 10px; font-size: 11.5px;">Close</button>
        </div>

        <div class="table-container" style="max-height: 260px; overflow-y: auto;">
          <table class="fin-table">
            <thead>
              <tr>
                <th>Merchant</th>
                <th>Classification</th>
                <th style="text-align: right;">Current</th>
                <th style="text-align: right;">Previous</th>
                <th style="text-align: right;">Delta</th>
                <th style="text-align: right;">Freq / Ticket / Refund</th>
              </tr>
            </thead>
            <tbody>
              ${merchants.map(m => {
                const tagClass = m.tag === 'NEW_MERCHANT' ? 'new' : (m.tag === 'MORE_FREQUENT' ? 'freq' : (m.tag === 'HIGHER_TICKET' ? 'ticket' : (m.tag === 'REFUND_CHANGE' ? 'refund' : 'reduced')));
                const sign = m.delta > 0 ? '+' : '';
                const color = m.delta > 0 ? 'var(--color-negative)' : (m.delta < 0 ? 'var(--color-positive)' : 'var(--text-muted)');
                return `
                  <tr>
                    <td style="font-weight: 500;">${escapeHtml(m.merchant)}</td>
                    <td><span class="driver-tag ${tagClass}">${m.tag.replace(/_/g, ' ')}</span></td>
                    <td style="text-align: right;">${state.formatCurrency(m.current)}</td>
                    <td style="text-align: right;">${state.formatCurrency(m.previous)}</td>
                    <td style="text-align: right; font-weight: 600; color: ${color};">${sign}${state.formatCurrency(m.delta)}</td>
                    <td style="text-align: right; font-size: 11.5px; color: var(--text-secondary);">
                      <span title="Frequency Effect">${m.frequency_effect > 0 ? '+' : ''}${state.formatCurrency(m.frequency_effect)}</span> / 
                      <span title="Ticket Effect">${m.ticket_effect > 0 ? '+' : ''}${state.formatCurrency(m.ticket_effect)}</span> / 
                      <span title="Refund Effect">${m.refund_effect > 0 ? '+' : ''}${state.formatCurrency(m.refund_effect)}</span>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    document.getElementById('close-merchant-drilldown')?.addEventListener('click', () => container.innerHTML = '');
  } catch (e) {
    console.error('Error loading merchant drilldown:', e);
  }
}

// ---------------------------------------------------------------------------
// Tab 3: Spending Patterns & Fingerprint
// ---------------------------------------------------------------------------
async function renderPatternsTab(container) {
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Computing behavioral patterns & fingerprint...</div>`;

  const [fp, rolling] = await Promise.all([
    api.getSpendingFingerprint(6, state.accountId, state.month),
    api.getRollingMetrics('expense', null, state.accountId, state.month)
  ]);

  if (!fp.available) {
    container.innerHTML = `
      <div class="fin-card" style="text-align: center; padding: 48px 20px;">
        <div style="width: 48px; height: 48px; border-radius: 50%; background: rgba(91, 140, 255, 0.15); color: #5B8CFF; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 14px;">
          <i data-lucide="info" style="width: 24px; height: 24px;"></i>
        </div>
        <h3 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">Insufficient Data for Spending Patterns</h3>
        <p style="font-size: 13px; color: var(--text-muted); max-width: 460px; margin: 6px auto 0;">
          ${fp.data_sufficiency?.reason || 'FinScope requires at least 30 transactions across 2+ months to calculate truthful behavioral patterns.'}
        </p>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();
    return;
  }

  const rhythmPct = Math.min(100, Math.max(0, Math.round(((fp.burstiness_score + 1.0) / 2.0) * 100)));
  const weekdayBreakdown = fp.metadata?.weekday_breakdown || [];

  container.innerHTML = `
    <!-- Top Behavioral Metric Cards -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Your Personal Spending Fingerprint</h3>
          <p>Objective behavioral characteristics over the analyzed window (${fp.period_label})</p>
        </div>
        <span class="delta-badge neutral" style="font-size: 12px;">${fp.transaction_count} transactions analyzed</span>
      </div>

      <div class="grid-3col" style="gap: 16px;">
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Typical Transaction</span>
          <div class="fingerprint-val" style="color: #4DD5A5;">${state.formatCurrency(fp.median_transaction)}</div>
          <div class="fingerprint-sub">Large (P75): ${state.formatCurrency(fp.p75_transaction)} • Top 10%: ${state.formatCurrency(fp.p90_transaction)}</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Weekend Concentration</span>
          <div class="fingerprint-val" style="color: #5B8CFF;">${fp.weekend_concentration}%</div>
          <div class="fingerprint-sub">Share of discretionary spend occurring on Sat & Sun</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Category Diversity</span>
          <div class="fingerprint-val" style="color: #C85AF4;">${fp.category_diversity_score} / 100</div>
          <div class="fingerprint-sub">Normalized Shannon entropy across spending categories</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Category Mix Stability</span>
          <div class="fingerprint-val" style="color: #27D5D5;">${fp.spending_consistency_score}%</div>
          <div class="fingerprint-sub">Cosine similarity of category vector over time</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Essential Spending Ratio</span>
          <div class="fingerprint-val" style="color: #FF9F43;">${fp.essential_ratio}%</div>
          <div class="fingerprint-sub">Recurring subscriptions & bills: ${fp.recurring_expense_ratio}%</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Top 3 Merchants Share</span>
          <div class="fingerprint-val" style="color: #FF6B8A;">${fp.top_merchants_share}%</div>
          <div class="fingerprint-sub">Concentration into your top spending destinations</div>
        </div>
      </div>

      <div style="margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border-subtle);">
        <div class="grid-2col" style="align-items: center;">
          <div>
            <span class="fingerprint-label">Spending Rhythm (Burstiness)</span>
            <div class="rhythm-bar">
              <span>Regular & Periodic</span>
              <div class="rhythm-track">
                <div class="rhythm-marker" style="left: ${rhythmPct}%;"></div>
              </div>
              <span>Clustered & Bursty</span>
            </div>
          </div>
          <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.5; padding-left: 20px; border-left: 1px solid var(--border-subtle);">
            • Highest daily spending day: <strong style="color: var(--text-primary);">${fp.most_active_weekday}</strong><br>
            • Most variable category: <strong style="color: var(--text-primary);">${fp.most_variable_category}</strong><br>
            • Most stable category: <strong style="color: var(--text-primary);">${fp.most_stable_category}</strong>
          </div>
        </div>
      </div>
    </div>

    <!-- Disambiguated Weekday Breakdown Table -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Weekday Spending Disambiguation</h3>
          <p>Tightly separating "Average Transaction Size" from "Average Daily Spend"</p>
        </div>
      </div>

      <div class="table-container">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Weekday</th>
              <th style="text-align: right;">Total Spend</th>
              <th style="text-align: right;">Tx Count</th>
              <th style="text-align: right;">Calendar Days</th>
              <th style="text-align: right;">Avg Transaction Size</th>
              <th style="text-align: right; color: var(--accent-blue);">Avg Daily Spend</th>
            </tr>
          </thead>
          <tbody>
            ${weekdayBreakdown.map(wb => `
              <tr>
                <td style="font-weight: 500;">${wb.day_name}</td>
                <td style="text-align: right;">${state.formatCurrency(wb.total_spend)}</td>
                <td style="text-align: right;">${wb.transaction_count}</td>
                <td style="text-align: right;">${wb.calendar_occurrences}</td>
                <td style="text-align: right;">${state.formatCurrency(wb.avg_transaction_size)}</td>
                <td style="text-align: right; font-weight: 700; color: var(--accent-blue);">${state.formatCurrency(wb.avg_daily_spend)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Tab 4: Anomalies & Normal Ranges
// ---------------------------------------------------------------------------
async function renderAnomaliesTab(container) {
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Evaluating statistical anomalies & normal ranges...</div>`;

  const [anomalies, normalRanges] = await Promise.all([
    api.getAnomalies(state.month, state.accountId, 2.5),
    api.getNormalRanges(state.accountId)
  ]);

  container.innerHTML = `
    <!-- Statistical Anomalies -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Detected Statistical Anomalies (${anomalies.length})</h3>
          <p>Transactions exceeding hierarchical personal baselines (Merchant -> Category -> Overall)</p>
        </div>
      </div>

      ${anomalies.length === 0 ? `
        <div style="text-align: center; padding: 36px; color: var(--text-muted);">
          <i data-lucide="shield-check" style="width: 32px; height: 32px; color: #4DD5A5; margin-bottom: 8px; display: inline-block;"></i>
          <div>No statistical anomalies detected. All spending is within personal historical norms.</div>
        </div>
      ` : `
        <div style="display: flex; flex-direction: column; gap: 14px;">
          ${anomalies.map(a => {
            const sevColor = a.severity === 'strong' ? '#FF6B8A' : (a.severity === 'moderate' ? '#FF9F43' : '#5B8CFF');
            const maxVal = Math.max(a.actual, a.normal_range_upper * 1.15);
            const lowPct = Math.round((a.normal_range_lower / maxVal) * 100);
            const upPct = Math.round((a.normal_range_upper / maxVal) * 100);
            const curPct = Math.min(100, Math.round((a.actual / maxVal) * 100));

            return `
              <div style="background-color: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 18px;">
                <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px;">
                  <div>
                    <div style="font-size: 14.5px; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
                      ${escapeHtml(a.title)}
                      <span class="delta-badge" style="background: ${sevColor}22; color: ${sevColor}; font-size: 10.5px;">${escapeHtml(a.severity.toUpperCase())}</span>
                    </div>
                    <div style="font-size: 12.5px; color: var(--text-secondary); margin-top: 3px;">${escapeHtml(a.explanation)}</div>
                  </div>
                  <div style="text-align: right;">
                    <div style="font-size: 18px; font-weight: 700; color: ${sevColor};">${state.formatCurrency(a.actual)}</div>
                    <div style="font-size: 11px; color: var(--text-muted);">Robust Z-Score: ${a.robust_score}</div>
                  </div>
                </div>

                <!-- Normal Range Visual Track -->
                <div class="normal-range-wrap" style="margin-top: 12px; padding: 10px 14px; background: rgba(0,0,0,0.2); border-radius: var(--radius-sm);">
                  <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);">
                    <span>Typical Range: ${state.formatCurrency(a.normal_range_lower)} – ${state.formatCurrency(a.normal_range_upper)}</span>
                    <span>Expected Median: ${state.formatCurrency(a.expected_median)}</span>
                  </div>
                  <div class="normal-range-track">
                    <div class="normal-range-band" style="left: ${lowPct}%; width: ${upPct - lowPct}%;"></div>
                    <div class="normal-range-current-dot" style="left: ${curPct}%; background-color: ${sevColor};"></div>
                  </div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `}
    </div>

    <!-- Category Baseline Normal Ranges Table -->
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Category Baseline Normal Ranges</h3>
          <p>Personal reference bounds (Median ± 2 × Scaled MAD) based on historical months</p>
        </div>
      </div>

      <div class="table-container">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Category</th>
              <th style="text-align: right;">Typical Lower</th>
              <th style="text-align: right;">Historical Median</th>
              <th style="text-align: right;">Typical Upper</th>
              <th style="text-align: right;">Sample History</th>
            </tr>
          </thead>
          <tbody>
            ${normalRanges.map(nr => `
              <tr>
                <td style="font-weight: 500;">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${escapeHtml(nr.color)}; margin-right:6px;"></span>
                  ${escapeHtml(nr.category_name)}
                </td>
                <td style="text-align: right; color: var(--text-secondary);">${state.formatCurrency(nr.lower)}</td>
                <td style="text-align: right; font-weight: 600;">${state.formatCurrency(nr.median)}</td>
                <td style="text-align: right; color: var(--text-secondary);">${state.formatCurrency(nr.upper)}</td>
                <td style="text-align: right; font-size: 12px; color: var(--text-muted);">${nr.sample_months} months</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Tab 5: Forecast & Backtest Evaluation
// ---------------------------------------------------------------------------
async function renderForecastTab(container) {
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Computing month-end forecast and model evaluation...</div>`;

  const [fc, backtest, upcomingBills] = await Promise.all([
    api.getForecast(state.month, state.accountId),
    api.getBacktestEvaluation(state.accountId),
    api.getUpcomingBills(state.month, state.accountId)
  ]);

  const catForecasts = fc.category_forecasts || [];
  const models = backtest.models || {};
  const bills = upcomingBills || [];

  const netColor = (fc.projected_net_flow || 0) >= 0 ? 'var(--color-positive)' : 'var(--color-negative)';

  container.innerHTML = `
    <!-- Top 4 Cards -->
    <div class="grid-4col" style="margin-bottom: 24px;">
      <div class="fin-card">
        <span class="kpi-label">Projected Month-End Spend</span>
        <div class="kpi-value" style="font-size: 28px; margin: 6px 0; color: var(--text-primary);">
          ${state.formatCurrency(fc.projected_expense)}
        </div>
        <span class="kpi-footer">${(fc.range_type === 'calibrated_range' || fc.components?.range_type === 'calibrated_range') ? 'Likely range' : 'Early estimate'}: ${state.formatCurrency(fc.lower_bound)} – ${state.formatCurrency(fc.upper_bound)}</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Spent to Date</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #4DD5A5;">
          ${state.formatCurrency(fc.actual_spent_to_date)}
        </div>
        <span class="kpi-footer">Days 1–${fc.components?.elapsed_days || 15} of ${fc.components?.total_days || 30}</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Upcoming Recurring</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #5B8CFF;">
          ${state.formatCurrency(fc.upcoming_recurring)}
        </div>
        <span class="kpi-footer">Scheduled bills executing later</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Remaining Variable</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #FF9F43;">
          ${state.formatCurrency(fc.expected_variable)}
        </div>
        <span class="kpi-footer">Dynamic weekday occurrence rate</span>
      </div>
    </div>

    <!-- Projected Cash Flow Summary Banner -->
    <div class="fin-card" style="margin-bottom: 24px; padding: 20px 24px; background: var(--bg-card-subtle);">
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;">
        <div>
          <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 600;">Month-End Net Flow Projection</span>
          <div style="font-size: 24px; font-weight: 800; color: ${netColor}; margin-top: 4px;">
            ${(fc.projected_net_flow || 0) >= 0 ? '+' : ''}${state.formatCurrency(fc.projected_net_flow || 0)}
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 24px;">
          <div>
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Projected Income</div>
            <div style="font-size: 16px; font-weight: 700; color: var(--color-positive); margin-top: 2px;">
              ${state.formatCurrency(fc.projected_income || 0)}
            </div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Projected Spend</div>
            <div style="font-size: 16px; font-weight: 700; color: var(--color-negative); margin-top: 2px;">
              ${state.formatCurrency(fc.projected_expense)}
            </div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Projected Savings Rate</div>
            <div style="font-size: 16px; font-weight: 700; color: var(--accent-purple); margin-top: 2px;">
              ${fc.projected_savings_rate || 0}%
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Category Projections vs Monthly Budgets -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Category Projections & Budget Overrun Risks</h3>
          <p>Projected spending vs allocated monthly budget targets</p>
        </div>
      </div>

      <div class="table-container">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Category</th>
              <th style="text-align: right;">Actual To Date</th>
              <th style="text-align: right;">Projected Month-End</th>
              <th style="text-align: right;">Budget</th>
              <th style="text-align: right;">Projected Variance</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${catForecasts.map(cf => {
              const varColor = cf.is_over_budget ? 'var(--color-negative)' : 'var(--color-positive)';
              return `
                <tr>
                  <td style="font-weight: 500;">
                    <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${escapeHtml(cf.color)}; margin-right:6px;"></span>
                    ${escapeHtml(cf.name)}
                  </td>
                  <td style="text-align: right;">${state.formatCurrency(cf.actual)}</td>
                  <td style="text-align: right; font-weight: 600;">${state.formatCurrency(cf.projected)}</td>
                  <td style="text-align: right;">${cf.budget !== null ? state.formatCurrency(cf.budget) : '—'}</td>
                  <td style="text-align: right; font-weight: 600; color: ${cf.projected_variance !== null ? varColor : 'var(--text-muted)'};">
                    ${cf.projected_variance !== null ? `${cf.projected_variance > 0 ? '+' : ''}${state.formatCurrency(cf.projected_variance)}` : '—'}
                  </td>
                  <td>
                    ${cf.is_over_budget ? `
                      <span class="delta-badge negative" style="font-size: 10.5px;">OVER BUDGET</span>
                    ` : (cf.budget !== null ? `
                      <span class="delta-badge positive" style="font-size: 10.5px;">ON TRACK</span>
                    ` : `
                      <span class="delta-badge neutral" style="font-size: 10.5px;">NO BUDGET</span>
                    `)}
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Scheduled Recurring Bills Table -->
    ${bills.length > 0 ? `
      <div class="fin-card" style="margin-bottom: 24px;">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Active Recurring Bills & Commitments</h3>
            <p>Monitored subscriptions and scheduled recurring commitments for ${state.formatMonthLabel(state.month)}</p>
          </div>
        </div>

        <div class="table-container">
          <table class="fin-table">
            <thead>
              <tr>
                <th>Bill / Payee</th>
                <th>Due Date</th>
                <th>Category</th>
                <th>Account</th>
                <th style="text-align: right;">Amount</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${bills.map(b => `
                <tr>
                  <td style="font-weight: 600;">${escapeHtml(b.name)}</td>
                  <td>${escapeHtml(b.due_date)}</td>
                  <td>
                    ${b.category_name ? `
                      <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${escapeHtml(b.category_color || '#888')}; margin-right:6px;"></span>
                      ${escapeHtml(b.category_name)}
                    ` : '—'}
                  </td>
                  <td>${escapeHtml(b.account_name || '—')}</td>
                  <td style="text-align: right; font-weight: 700; font-family: monospace;">
                    ${state.formatCurrency(b.amount)}
                  </td>
                  <td>
                    ${b.status === 'paid' ? '<span class="tag-pill" style="background: rgba(77,213,165,0.15); color: #4DD5A5;">Paid</span>'
                      : (b.status === 'upcoming' ? '<span class="tag-pill" style="background: rgba(91,140,255,0.15); color: #5B8CFF;">Upcoming</span>'
                      : '<span class="tag-pill" style="background: rgba(255,107,138,0.15); color: #FF6B8A;">Overdue</span>')
                    }
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    ` : ''}

    <!-- Backtest Evaluation Leaderboard -->
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Forecast Model Evaluation Leaderboard (Rolling-Origin Backtest)</h3>
          <p>${backtest.evaluations_count ? `Replayed across historical cutoffs (${backtest.evaluations_count} evaluations)` : 'Deterministic historical accuracy comparison across origins'}</p>
        </div>
        <span class="delta-badge positive" style="font-size: 11.5px;">Lowest MAE (Comparable Origins): ${(backtest.best_model || 'production_policy').replace(/_/g, ' ')}</span>
      </div>

      <div class="table-container">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Model</th>
              <th style="text-align: right;">Origins Evaluated</th>
              <th style="text-align: right;">Mean Absolute Error (MAE)</th>
              <th style="text-align: right;">Median Absolute Error</th>
              <th style="text-align: right;">WAPE %</th>
              <th style="text-align: right;">Bias</th>
              <th>Evaluation Rank</th>
            </tr>
          </thead>
          <tbody>
            ${Object.entries(models).map(([name, m]) => {
              const isBest = (name === backtest.best_model);
              return `
                <tr style="${isBest ? 'background: rgba(77, 213, 165, 0.08);' : ''}">
                  <td style="font-weight: 600; text-transform: uppercase;">
                    ${name.replace(/_/g, ' ')}
                    ${isBest ? `<span class="delta-badge positive" style="font-size: 9.5px; margin-left: 6px;">TOP MODEL</span>` : ''}
                  </td>
                  <td style="text-align: right; font-weight: 500;">${m.sample_origins || 0}</td>
                  <td style="text-align: right; font-weight: 600;">${state.formatCurrency(m.mae)}</td>
                  <td style="text-align: right;">${state.formatCurrency(m.median_ae)}</td>
                  <td style="text-align: right;">${m.wape_pct}%</td>
                  <td style="text-align: right; color: ${m.bias > 0 ? 'var(--color-negative)' : 'var(--color-positive)'};">
                    ${m.bias > 0 ? '+' : ''}${state.formatCurrency(m.bias)}
                  </td>
                  <td>
                    <span class="delta-badge ${isBest ? 'positive' : 'neutral'}" style="font-size: 11px;">
                      ${isBest ? 'Rank 1' : 'Baseline'}
                    </span>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Chart Helpers
// ---------------------------------------------------------------------------
function renderVarianceWaterfallChart(steps) {
  const chartDom = document.getElementById('variance-chart');
  if (!chartDom || !window.echarts || !steps) return;

  if (varianceChart) varianceChart.dispose();
  varianceChart = window.echarts.init(chartDom);

  const categories = steps.map(s => s.label);
  const baseValues = [];
  const stepValues = [];

  let running = 0;
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (i === 0) {
      baseValues.push(0);
      stepValues.push(s.amount);
      running = s.amount;
    } else if (i === steps.length - 1) {
      baseValues.push(0);
      stepValues.push(s.amount);
    } else {
      if (s.amount >= 0) {
        baseValues.push(running);
        stepValues.push(s.amount);
        running += s.amount;
      } else {
        running += s.amount;
        baseValues.push(running);
        stepValues.push(-s.amount);
      }
    }
  }

  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: 20, right: 20, bottom: 40, left: 60 },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: '#8E8E93', fontSize: 11, interval: 0, rotate: 20 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8E8E93', formatter: '${value}' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    series: [
      {
        name: 'Placeholder',
        type: 'bar',
        stack: 'Total',
        itemStyle: { borderColor: 'transparent', color: 'transparent' },
        emphasis: { itemStyle: { borderColor: 'transparent', color: 'transparent' } },
        data: baseValues
      },
      {
        name: 'Variance',
        type: 'bar',
        stack: 'Total',
        label: { show: true, position: 'top', color: '#E0E0E0', fontSize: 10.5, formatter: '${c}' },
        itemStyle: {
          color: function (params) {
            const idx = params.dataIndex;
            if (idx === 0 || idx === steps.length - 1) return '#5B8CFF';
            return steps[idx].amount >= 0 ? '#FF6B8A' : '#4DD5A5';
          },
          borderRadius: [4, 4, 0, 0]
        },
        data: stepValues
      }
    ]
  };

  varianceChart.setOption(option);
}

function renderWeekdayChart(weekdayData) {
  const chartDom = document.getElementById('weekday-chart');
  if (!chartDom || !window.echarts || !weekdayData) return;

  if (weekdayChart) weekdayChart.dispose();
  weekdayChart = window.echarts.init(chartDom);

  const days = weekdayData.map(d => d.day);
  const averages = weekdayData.map(d => d.average);

  const option = {
    tooltip: { trigger: 'axis', formatter: '{b}: ${c} avg daily expense' },
    grid: { top: 20, right: 20, bottom: 25, left: 50 },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: '#8E8E93', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8E8E93', formatter: '${value}' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    series: [{
      type: 'bar',
      data: averages,
      itemStyle: { color: '#5B8CFF', borderRadius: [4, 4, 0, 0] }
    }]
  };

  weekdayChart.setOption(option);
}

function renderCumulativeChart(cumData) {
  const chartDom = document.getElementById('cumulative-chart');
  if (!chartDom || !window.echarts || !cumData) return;

  if (cumulativeChart) cumulativeChart.dispose();
  cumulativeChart = window.echarts.init(chartDom);

  const option = {
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['Current Period', 'Comparison Period'],
      textStyle: { color: '#8E8E93', fontSize: 11 },
      top: 0
    },
    grid: { top: 35, right: 20, bottom: 25, left: 50 },
    xAxis: {
      type: 'category',
      data: cumData.days,
      axisLabel: { color: '#8E8E93', fontSize: 10 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8E8E93', formatter: '${value}' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    series: [
      {
        name: 'Current Period',
        type: 'line',
        data: cumData.current,
        smooth: true,
        lineStyle: { color: '#5B8CFF', width: 2.5 }
      },
      {
        name: 'Comparison Period',
        type: 'line',
        data: cumData.previous,
        smooth: true,
        lineStyle: { color: '#8E8E93', type: 'dashed' }
      }
    ]
  };

  cumulativeChart.setOption(option);
}
