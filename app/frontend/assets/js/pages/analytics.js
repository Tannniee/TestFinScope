/**
 * FinScope Analytics Engine Core Workspace Page
 * Tabs:
 * 1. What Changed? v2 (Driver & Frequency vs Ticket Decomposition)
 * 2. Spending Fingerprint (Behavioral Metrics, Diversity & Rhythm)
 * 3. Anomalies & Normal Ranges (Robust Z-Scores & Typical Ranges)
 * 4. Forecast & Baselines (Explainable Component Forecast & Rolling Norms)
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';

let varianceChart = null;
let weekdayChart = null;
let cumulativeChart = null;
let forecastChart = null;

let currentTab = 'changes'; // 'changes', 'fingerprint', 'anomalies', 'forecast'

export async function renderAnalyticsPage(container) {
  container.innerHTML = `
    <div class="analytics-view">
      <!-- Navigation Tabs -->
      <div class="analytics-tab-bar">
        <button class="analytics-tab-btn ${currentTab === 'changes' ? 'active' : ''}" data-tab="changes">
          <i data-lucide="git-commit"></i> What Changed? v2
        </button>
        <button class="analytics-tab-btn ${currentTab === 'fingerprint' ? 'active' : ''}" data-tab="fingerprint">
          <i data-lucide="fingerprint"></i> Spending Fingerprint
        </button>
        <button class="analytics-tab-btn ${currentTab === 'anomalies' ? 'active' : ''}" data-tab="anomalies">
          <i data-lucide="alert-octagon"></i> Anomalies & Normal Ranges
        </button>
        <button class="analytics-tab-btn ${currentTab === 'forecast' ? 'active' : ''}" data-tab="forecast">
          <i data-lucide="trending-up"></i> Forecast & Rolling Baselines
        </button>
      </div>

      <!-- Tab Content Containers -->
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
      loadTabContent();
    });
  });

  await loadTabContent();
}

async function loadTabContent() {
  const content = document.getElementById('analytics-tab-content');
  if (!content) return;

  try {
    if (currentTab === 'changes') {
      await renderChangesTab(content);
    } else if (currentTab === 'fingerprint') {
      await renderFingerprintTab(content);
    } else if (currentTab === 'anomalies') {
      await renderAnomaliesTab(content);
    } else if (currentTab === 'forecast') {
      await renderForecastTab(content);
    }
  } catch (err) {
    console.error('Error rendering analytics tab:', err);
    content.innerHTML = `<div style="text-align:center; color: var(--color-negative); padding: 30px;">Error loading analytics: ${err.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Tab 1: What Changed? v2 (Frequency vs Ticket Decomposition)
// ---------------------------------------------------------------------------
async function renderChangesTab(container) {
  container.innerHTML = `
    <div style="text-align: center; color: var(--text-muted); padding: 30px;">Analyzing variance drivers...</div>
  `;

  const [changes, deepDive] = await Promise.all([
    api.getWhatChanged(state.month, null, state.accountId),
    api.getAnalyticsDeepDive(state.month, state.accountId)
  ]);

  const totalDelta = changes.total_delta;
  const deltaSign = totalDelta > 0 ? '+' : '';
  const freqEffect = changes.overall_frequency_effect;
  const ticketEffect = changes.overall_ticket_effect;
  const freqSign = freqEffect > 0 ? '+' : '';
  const ticketSign = ticketEffect > 0 ? '+' : '';

  container.innerHTML = `
    <!-- Summary Header Cards -->
    <div class="grid-4col" style="margin-bottom: 24px;">
      <div class="fin-card">
        <span class="kpi-label">Total Spend Change</span>
        <div class="kpi-value ${totalDelta > 0 ? 'text-negative' : 'text-positive'}" style="font-size: 26px; margin: 6px 0;">
          ${deltaSign}${state.formatCurrency(totalDelta)}
        </div>
        <span class="kpi-footer">vs ${changes.comparison_month}</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Frequency Effect</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #5B8CFF;">
          ${freqSign}${state.formatCurrency(freqEffect)}
        </div>
        <span class="kpi-footer">Change due to transaction volume</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Ticket Size Effect</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #FF9F43;">
          ${ticketSign}${state.formatCurrency(ticketEffect)}
        </div>
        <span class="kpi-footer">Change due to average purchase size</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Weekend Shift</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #C85AF4;">
          ${changes.weekend_delta > 0 ? '+' : ''}${state.formatCurrency(changes.weekend_delta)}
        </div>
        <span class="kpi-footer">Weekend vs weekday variance</span>
      </div>
    </div>

    <!-- Waterfall & Drivers Table -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Category Driver Decomposition</h3>
          <p>Exact decomposition: Frequency Effect + Ticket Effect = Total Delta</p>
        </div>
      </div>

      <div class="grid-2col" style="grid-template-columns: 1.2fr 1fr; gap: 24px;">
        <div id="variance-chart" style="width: 100%; height: 340px;"></div>
        <div class="table-container" style="max-height: 340px; overflow-y: auto;">
          <table class="fin-table">
            <thead>
              <tr>
                <th>Driver</th>
                <th>Classification</th>
                <th style="text-align: right;">Delta</th>
                <th style="text-align: right;">Freq / Ticket</th>
              </tr>
            </thead>
            <tbody id="changes-table-body"></tbody>
          </table>
        </div>
      </div>
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
            <p>Trajectory compared with previous month</p>
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
      const tagClass = d.tag === 'NEW' ? 'new' : (d.tag === 'INCREASED_FREQUENCY' ? 'freq' : (d.tag === 'HIGHER_TICKET' ? 'ticket' : 'reduced'));
      const sign = d.delta > 0 ? '+' : '';
      const color = d.delta > 0 ? 'var(--color-negative)' : (d.delta < 0 ? 'var(--color-positive)' : 'var(--text-muted)');

      return `
        <tr>
          <td style="font-weight: 500;">
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${d.color}; margin-right:6px;"></span>
            ${d.name}
          </td>
          <td><span class="driver-tag ${tagClass}">${d.tag.replace(/_/g, ' ')}</span></td>
          <td style="text-align: right; font-weight: 600; color: ${color};">${sign}${state.formatCurrency(d.delta)}</td>
          <td style="text-align: right; font-size: 11.5px; color: var(--text-secondary);">
            <span title="Frequency Effect">${d.frequency_effect > 0 ? '+' : ''}${state.formatCurrency(d.frequency_effect)}</span> / 
            <span title="Ticket Size Effect">${d.ticket_effect > 0 ? '+' : ''}${state.formatCurrency(d.ticket_effect)}</span>
          </td>
        </tr>
      `;
    }).join('');
  }

  renderVarianceWaterfallChart(changes.waterfall);
  renderWeekdayChart(deepDive.weekday);
  renderCumulativeChart(deepDive.cumulative);
}

// ---------------------------------------------------------------------------
// Tab 2: Spending Fingerprint
// ---------------------------------------------------------------------------
async function renderFingerprintTab(container) {
  container.innerHTML = `
    <div style="text-align: center; color: var(--text-muted); padding: 30px;">Computing spending fingerprint...</div>
  `;

  const fp = await api.getSpendingFingerprint(6, state.accountId);
  if (fp.error) {
    container.innerHTML = `<div class="fin-card" style="text-align: center; padding: 40px; color: var(--text-muted);">${fp.error}</div>`;
    return;
  }

  // Rhythm marker position: -1.0 is 0%, 0.0 is 50%, +1.0 is 100%
  const rhythmPct = Math.min(100, Math.max(0, Math.round(((fp.burstiness_score + 1.0) / 2.0) * 100)));

  container.innerHTML = `
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Your Personal Spending Fingerprint</h3>
          <p>Objective behavioral characteristics over the past 6 months (${fp.period_label})</p>
        </div>
        <span class="delta-badge neutral" style="font-size: 12px;">${fp.transaction_count} transactions analyzed</span>
      </div>

      <!-- Fingerprint Grid -->
      <div class="grid-3col" style="gap: 16px;">
        <!-- Card 1: Typical Transaction -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Typical Transaction</span>
          <div class="fingerprint-val" style="color: #4DD5A5;">${state.formatCurrency(fp.median_transaction)}</div>
          <div class="fingerprint-sub">
            Large (P75): ${state.formatCurrency(fp.p75_transaction)} • Top 10%: ${state.formatCurrency(fp.p90_transaction)}
          </div>
        </div>

        <!-- Card 2: Weekend Concentration -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Weekend Concentration</span>
          <div class="fingerprint-val" style="color: #5B8CFF;">${fp.weekend_concentration}%</div>
          <div class="fingerprint-sub">Share of discretionary spend occurring on Sat & Sun</div>
        </div>

        <!-- Card 3: Category Diversity -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Category Diversity</span>
          <div class="fingerprint-val" style="color: #C85AF4;">${fp.category_diversity_score} / 100</div>
          <div class="fingerprint-sub">Shannon entropy spread across spending categories</div>
        </div>

        <!-- Card 4: Month-to-Month Stability -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Category Stability</span>
          <div class="fingerprint-val" style="color: #27D5D5;">${fp.spending_consistency_score}%</div>
          <div class="fingerprint-sub">Cosine similarity of category mix over time</div>
        </div>

        <!-- Card 5: Essential vs Discretionary -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Essential Spending Ratio</span>
          <div class="fingerprint-val" style="color: #FF9F43;">${fp.essential_ratio}%</div>
          <div class="fingerprint-sub">Recurring subscriptions & bills: ${fp.recurring_expense_ratio}%</div>
        </div>

        <!-- Card 6: Top Merchants Concentration -->
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Top 3 Merchants Share</span>
          <div class="fingerprint-val" style="color: #FF6B8A;">${fp.top_merchants_share}%</div>
          <div class="fingerprint-sub">Concentration into your top spending destinations</div>
        </div>
      </div>

      <!-- Rhythm & Behavioral Highlights -->
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
            • Most active spending day: <strong style="color: var(--text-primary);">${fp.most_active_weekday}</strong><br>
            • Most variable category: <strong style="color: var(--text-primary);">${fp.most_variable_category}</strong><br>
            • Most stable category: <strong style="color: var(--text-primary);">${fp.most_stable_category}</strong>
          </div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Tab 3: Anomalies & Normal Ranges
// ---------------------------------------------------------------------------
async function renderAnomaliesTab(container) {
  container.innerHTML = `
    <div style="text-align: center; color: var(--text-muted); padding: 30px;">Evaluating statistical anomalies & normal ranges...</div>
  `;

  const anomalies = await api.getAnomalies(state.month, state.accountId, 2.5);

  if (!anomalies || anomalies.length === 0) {
    container.innerHTML = `
      <div class="fin-card" style="text-align: center; padding: 48px 20px;">
        <div style="width: 48px; height: 48px; border-radius: 50%; background: rgba(77, 213, 165, 0.15); color: #4DD5A5; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 14px;">
          <i data-lucide="shield-check" style="width: 24px; height: 24px;"></i>
        </div>
        <h3 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">No Statistical Anomalies Detected</h3>
        <p style="font-size: 13px; color: var(--text-muted); max-width: 460px; margin: 6px auto 0;">All transactions and category totals for ${state.month} are well within your personal historical normal ranges.</p>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();
    return;
  }

  container.innerHTML = `
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Detected Statistical Anomalies (${anomalies.length})</h3>
          <p>Transactions and categories exceeding robust personal historical baselines (Median & Scaled MAD)</p>
        </div>
      </div>

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
                    ${a.title}
                    <span class="delta-badge" style="background: ${sevColor}22; color: ${sevColor}; font-size: 10.5px;">${a.severity.toUpperCase()}</span>
                  </div>
                  <div style="font-size: 12.5px; color: var(--text-secondary); margin-top: 3px;">${a.explanation}</div>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 18px; font-weight: 700; color: ${sevColor};">${state.formatCurrency(a.actual)}</div>
                  <div style="font-size: 11px; color: var(--text-muted);">Z-Score: ${a.robust_score}</div>
                </div>
              </div>

              <!-- Normal Range Visual Bar -->
              <div class="normal-range-wrap" style="margin-top: 12px; padding: 10px 14px; background: rgba(0,0,0,0.2); border-radius: var(--radius-sm);">
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);">
                  <span>Typical Range: ${state.formatCurrency(a.normal_range_lower)} – ${state.formatCurrency(a.normal_range_upper)}</span>
                  <span>Median: ${state.formatCurrency(a.expected_median)}</span>
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
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Tab 4: Forecast & Rolling Baselines
// ---------------------------------------------------------------------------
async function renderForecastTab(container) {
  container.innerHTML = `
    <div style="text-align: center; color: var(--text-muted); padding: 30px;">Calculating month-end projection...</div>
  `;

  const [fc, rolling] = await Promise.all([
    api.getForecast(state.month, state.accountId),
    api.getRollingMetrics('expense', null, state.accountId)
  ]);

  const projOver = fc.projected_variance;

  container.innerHTML = `
    <!-- Top Projection Cards -->
    <div class="grid-4col" style="margin-bottom: 24px;">
      <div class="fin-card">
        <span class="kpi-label">Projected Month-End</span>
        <div class="kpi-value" style="font-size: 28px; margin: 6px 0; color: var(--text-primary);">
          ${state.formatCurrency(fc.projected_expense)}
        </div>
        <span class="kpi-footer">Likely: ${state.formatCurrency(fc.lower_bound)} – ${state.formatCurrency(fc.upper_bound)}</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Actual Spent To Date</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #4DD5A5;">
          ${state.formatCurrency(fc.actual_spent_to_date)}
        </div>
        <span class="kpi-footer">Through Day ${fc.components.elapsed_days} of ${fc.components.total_days}</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Upcoming Recurring</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #5B8CFF;">
          ${state.formatCurrency(fc.upcoming_recurring)}
        </div>
        <span class="kpi-footer">Known bills scheduled later this month</span>
      </div>

      <div class="fin-card">
        <span class="kpi-label">Remaining Variable</span>
        <div class="kpi-value" style="font-size: 26px; margin: 6px 0; color: #FF9F43;">
          ${state.formatCurrency(fc.expected_variable)}
        </div>
        <span class="kpi-footer">Weekday-adjusted variable estimate</span>
      </div>
    </div>

    <!-- Category Budget Risks & Projections -->
    <div class="fin-card" style="margin-bottom: 24px;">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Category Projections & Budget Risks</h3>
          <p>Forecasted month-end outcome compared with monthly category budgets</p>
        </div>
        <span class="delta-badge ${fc.confidence === 'high' ? 'positive' : 'neutral'}">Confidence: ${fc.confidence.toUpperCase()}</span>
      </div>

      <div class="table-container">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Category</th>
              <th style="text-align: right;">Spent to Date</th>
              <th style="text-align: right;">Projected Month-End</th>
              <th style="text-align: right;">Budget</th>
              <th style="text-align: right;">Projected Variance</th>
            </tr>
          </thead>
          <tbody>
            ${(fc.category_forecasts || []).map(c => {
              const varColor = c.is_over_budget ? 'var(--color-negative)' : 'var(--color-positive)';
              return `
                <tr>
                  <td style="font-weight: 500;">
                    <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${c.color}; margin-right:6px;"></span>
                    ${c.name}
                  </td>
                  <td style="text-align: right;">${state.formatCurrency(c.actual)}</td>
                  <td style="text-align: right; font-weight: 600;">${state.formatCurrency(c.projected)}</td>
                  <td style="text-align: right; color: var(--text-muted);">${c.budget !== null ? state.formatCurrency(c.budget) : 'None'}</td>
                  <td style="text-align: right; font-weight: 600; color: ${varColor};">
                    ${c.projected_variance !== null ? (c.projected_variance > 0 ? '+' : '') + state.formatCurrency(c.projected_variance) : '—'}
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Historical Rolling Baselines Card -->
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Historical Rolling Baselines</h3>
          <p>Current month vs. personal historical averages and robust medians</p>
        </div>
      </div>

      <div class="grid-4col" style="gap: 16px;">
        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">3-Month Median</span>
          <div class="fingerprint-val">${state.formatCurrency(rolling.median_3)}</div>
          <div class="fingerprint-sub">Mean: ${state.formatCurrency(rolling.mean_3)}</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">6-Month Median</span>
          <div class="fingerprint-val">${state.formatCurrency(rolling.median_6)}</div>
          <div class="fingerprint-sub">Mean: ${state.formatCurrency(rolling.mean_6)}</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">EWMA (Span 3)</span>
          <div class="fingerprint-val">${state.formatCurrency(rolling.ewma_3)}</div>
          <div class="fingerprint-sub">Recent-weighted moving average</div>
        </div>

        <div class="fingerprint-card-metric">
          <span class="fingerprint-label">Typical Variation (MAD)</span>
          <div class="fingerprint-val">${state.formatCurrency(rolling.mad_6)}</div>
          <div class="fingerprint-sub">Normal monthly fluctuation</div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Chart Renderers (ECharts)
// ---------------------------------------------------------------------------
function renderVarianceWaterfallChart(steps) {
  const chartDom = document.getElementById('variance-chart');
  if (!chartDom || !window.echarts || !steps) return;

  if (varianceChart) varianceChart.dispose();
  varianceChart = window.echarts.init(chartDom);

  const labels = steps.map(s => s.label);
  const data = steps.map(s => s.amount);
  const colors = steps.map(s => s.is_total ? '#5B8CFF' : (s.amount >= 0 ? '#FF6B8A' : '#4DD5A5'));

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1E1E28',
      borderColor: '#2A2A38',
      textStyle: { color: '#F2F2F7', fontSize: 12 },
      formatter: (params) => {
        const item = params[0];
        const prefix = item.value > 0 ? '+' : '';
        return `${item.name}: <strong>${prefix}${state.formatCurrency(item.value)}</strong>`;
      }
    },
    grid: { top: 20, right: 20, bottom: 40, left: 65 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#2A2A38' } },
      axisLabel: { color: '#8E8E93', fontSize: 11, interval: 0, rotate: labels.length > 5 ? 20 : 0 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#2A2A38', type: 'dashed' } },
      axisLabel: { color: '#8E8E93', fontSize: 11, formatter: (val) => state.formatCurrency(val) }
    },
    series: [{
      type: 'bar',
      data: data.map((val, idx) => ({
        value: val,
        itemStyle: { color: colors[idx], borderRadius: [4, 4, 0, 0] }
      })),
      barMaxWidth: 36
    }]
  };

  varianceChart.setOption(option);
}

function renderWeekdayChart(weekdayData) {
  const chartDom = document.getElementById('weekday-chart');
  if (!chartDom || !window.echarts || !weekdayData) return;

  if (weekdayChart) weekdayChart.dispose();
  weekdayChart = window.echarts.init(chartDom);

  const days = weekdayData.map(d => d.day);
  const totals = weekdayData.map(d => d.total);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1E1E28',
      borderColor: '#2A2A38',
      textStyle: { color: '#F2F2F7', fontSize: 12 },
      formatter: (params) => `${params[0].name}: <strong>${state.formatCurrency(params[0].value)}</strong>`
    },
    grid: { top: 20, right: 20, bottom: 30, left: 60 },
    xAxis: {
      type: 'category',
      data: days,
      axisLine: { lineStyle: { color: '#2A2A38' } },
      axisLabel: { color: '#8E8E93', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#2A2A38', type: 'dashed' } },
      axisLabel: { color: '#8E8E93', fontSize: 11, formatter: (val) => state.formatCurrency(val) }
    },
    series: [{
      type: 'bar',
      data: totals,
      itemStyle: {
        color: (param) => (param.dataIndex >= 5 ? '#C85AF4' : '#5B8CFF'),
        borderRadius: [4, 4, 0, 0]
      },
      barMaxWidth: 28
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
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1E1E28',
      borderColor: '#2A2A38',
      textStyle: { color: '#F2F2F7', fontSize: 12 },
      formatter: (params) => {
        let res = `Day ${params[0].name}<br/>`;
        params.forEach(p => {
          res += `<span style="color:${p.color};">●</span> ${p.seriesName}: <strong>${state.formatCurrency(p.value)}</strong><br/>`;
        });
        return res;
      }
    },
    legend: {
      data: ['Current Month', 'Previous Month'],
      textStyle: { color: '#8E8E93', fontSize: 11 },
      top: 0
    },
    grid: { top: 35, right: 20, bottom: 30, left: 60 },
    xAxis: {
      type: 'category',
      data: cumData.days,
      axisLine: { lineStyle: { color: '#2A2A38' } },
      axisLabel: { color: '#8E8E93', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#2A2A38', type: 'dashed' } },
      axisLabel: { color: '#8E8E93', fontSize: 11, formatter: (val) => state.formatCurrency(val) }
    },
    series: [
      {
        name: 'Current Month',
        type: 'line',
        data: cumData.current,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: '#FF6B8A' },
        itemStyle: { color: '#FF6B8A' }
      },
      {
        name: 'Previous Month',
        type: 'line',
        data: cumData.previous,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, type: 'dashed', color: '#8E8E93' },
        itemStyle: { color: '#8E8E93' }
      }
    ]
  };

  cumulativeChart.setOption(option);
}
