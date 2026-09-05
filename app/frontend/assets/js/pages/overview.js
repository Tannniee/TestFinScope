/**
 * FinScope Overview Dashboard Page
 * Enhanced with Hero Card, Sparklines, Radial Progress, Avatars, and Count-up animations.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';
import { escapeHtml, getMerchantInitials, animateCountUp } from '../utils.js';
import {
  TOOLTIP_STYLE,
  AXIS_LABEL_STYLE,
  AXIS_LINE_STYLE,
  SPLIT_LINE_STYLE,
  GRID_TIGHT,
  verticalGradient
} from '../charts/chart-theme.js';
import { renderSparkline, renderRadialGauge, disposeChart } from '../charts/sparkline.js';

let trendChartInstance = null;
let donutChartInstance = null;
let dailyChartInstance = null;

export async function renderOverviewPage(container) {
  container.innerHTML = `
    <div class="overview-view">
      <!-- KPI Cards Row -->
      <div class="grid-5col" id="kpi-row" style="margin-bottom: 24px;">
        <div class="kpi-card stagger-in" id="kpi-income">
          <div class="kpi-header">
            <span class="kpi-label">Total Income</span>
            <div class="kpi-icon" style="background: rgba(77, 213, 165, 0.15); color: #4DD5A5;">
              <i data-lucide="arrow-down-left"></i>
            </div>
          </div>
          <div class="kpi-value amount-value num-tabular" id="kpi-income-val">$0.00</div>
          <div id="kpi-income-sparkline" class="kpi-sparkline"></div>
          <div class="kpi-footer">
            <span class="delta-badge neutral" id="kpi-income-delta">0%</span>
            <span>vs previous month</span>
          </div>
        </div>

        <div class="kpi-card stagger-in" id="kpi-expense">
          <div class="kpi-header">
            <span class="kpi-label">Total Expense</span>
            <div class="kpi-icon" style="background: rgba(255, 107, 138, 0.15); color: #FF6B8A;">
              <i data-lucide="arrow-up-right"></i>
            </div>
          </div>
          <div class="kpi-value amount-value num-tabular" id="kpi-expense-val">$0.00</div>
          <div id="kpi-expense-sparkline" class="kpi-sparkline"></div>
          <div class="kpi-footer">
            <span class="delta-badge neutral" id="kpi-expense-delta">0%</span>
            <span>vs previous month</span>
          </div>
        </div>

        <div class="kpi-card stagger-in" id="kpi-net">
          <div class="kpi-header">
            <span class="kpi-label">Net Cash Flow</span>
            <div class="kpi-icon" style="background: rgba(91, 140, 255, 0.15); color: #5B8CFF;">
              <i data-lucide="wallet"></i>
            </div>
          </div>
          <div class="kpi-value amount-value num-tabular" id="kpi-net-val">$0.00</div>
          <div id="kpi-net-sparkline" class="kpi-sparkline"></div>
          <div class="kpi-footer">
            <span id="kpi-net-status" style="color: var(--text-secondary);">Income - Expenses</span>
          </div>
        </div>

        <div class="kpi-card stagger-in" id="kpi-savings">
          <div class="kpi-header">
            <span class="kpi-label">Savings Rate</span>
            <div class="kpi-icon" style="background: rgba(200, 90, 244, 0.15); color: #C85AF4;">
              <i data-lucide="pie-chart"></i>
            </div>
          </div>
          <div class="kpi-savings-wrap">
            <div class="kpi-value num-tabular" id="kpi-savings-val">0.0%</div>
            <div id="kpi-savings-radial" class="kpi-radial-gauge"></div>
          </div>
          <div class="kpi-footer">
            <span id="kpi-savings-prev">Previous: 0.0%</span>
          </div>
        </div>

        <!-- Hero Card: Net Cash Position (Liquid balance across accounts) -->
        <div class="kpi-card kpi-card--hero stagger-in" id="kpi-net-cash">
          <div class="kpi-header">
            <span class="kpi-label">Net Cash Position</span>
            <div class="kpi-icon">
              <i data-lucide="landmark"></i>
            </div>
          </div>
          <div class="kpi-value amount-value num-tabular" id="kpi-net-cash-val">$0.00</div>
          <div id="kpi-net-cash-sparkline" class="kpi-sparkline"></div>
          <div class="kpi-footer">
            <span id="kpi-net-cash-sub">Liquid cash & balances</span>
          </div>
        </div>
      </div>

      <!-- Ranked Financial Insights Strip (Core Analytics Engine) -->
      <div id="overview-insights-strip" class="insight-strip"></div>

      <!-- Charts Section: Cash Flow Trend & Expense Breakdown -->
      <div class="grid-2col" style="grid-template-columns: 1.6fr 1fr; margin-bottom: 24px;">
        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Cash Flow Trend</h3>
              <p>Daily income vs. expense progression</p>
            </div>
          </div>
          <div id="trend-chart" style="width: 100%; height: 280px;"></div>
        </div>

        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Expense Breakdown</h3>
              <p>Spending distribution across categories</p>
            </div>
          </div>
          <div id="donut-chart" style="width: 100%; height: 280px;"></div>
        </div>
      </div>

      <!-- Daily Spending & Recent Transactions -->
      <div class="grid-2col" style="grid-template-columns: 1fr 1.3fr;">
        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Daily Spending</h3>
              <p>Expense intensity per day with peak day indicators</p>
            </div>
          </div>
          <div id="daily-chart" style="width: 100%; height: 260px;"></div>
        </div>

        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Recent Activity</h3>
              <p>Latest transactions recorded</p>
            </div>
            <a href="#transactions" class="btn btn-secondary btn-sm">View All</a>
          </div>
          <div class="table-container" style="max-height: 260px; overflow-y: auto;">
            <table class="fin-table" id="recent-tx-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Merchant / Description</th>
                  <th>Category</th>
                  <th style="text-align: right;">Amount</th>
                </tr>
              </thead>
              <tbody id="recent-tx-body">
                <tr><td colspan="4" style="padding: 16px 12px;"><div class="skeleton skeleton-line" style="width: 85%;"></div></td></tr>
                <tr><td colspan="4" style="padding: 16px 12px;"><div class="skeleton skeleton-line" style="width: 70%;"></div></td></tr>
                <tr><td colspan="4" style="padding: 16px 12px;"><div class="skeleton skeleton-line" style="width: 90%;"></div></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  await loadDashboardData();
}

async function loadDashboardData() {
  try {
    const [summary, recentTxs, insightsData, accounts] = await Promise.all([
      api.getMonthSummary(state.month, state.accountId),
      api.getTransactions({ month: state.month, account_id: state.accountId, limit: 6 }),
      api.getRankedInsights(state.month, state.accountId, 4),
      api.getAccounts()
    ]);

    if (Array.isArray(accounts)) {
      state.accounts = accounts;
    }

    renderKPIs(summary.kpis, accounts, summary.trend);
    renderRankedInsights(insightsData ? insightsData.insights : []);
    renderTrendChart(summary.trend);
    renderDonutChart(summary.categories);
    renderDailyChart(summary.trend);
    renderRecentTransactions(recentTxs.items);
  } catch (err) {
    console.error('Error loading dashboard data:', err);
    showToast('Failed to load dashboard data', 'error');
  }
}

function renderRankedInsights(insights) {
  const container = document.getElementById('overview-insights-strip');
  if (!container) return;

  if (!insights || insights.length === 0) {
    container.innerHTML = '';
    return;
  }

  const sevIcons = {
    critical: { icon: 'alert-triangle', color: '#FF6B8A', bg: 'rgba(255, 107, 138, 0.15)' },
    warning: { icon: 'alert-circle', color: '#FF9F43', bg: 'rgba(255, 159, 67, 0.15)' },
    success: { icon: 'check-circle-2', color: '#4DD5A5', bg: 'rgba(77, 213, 165, 0.15)' },
    info: { icon: 'sparkles', color: '#5B8CFF', bg: 'rgba(91, 140, 255, 0.15)' }
  };

  container.innerHTML = insights.map((ins, idx) => {
    const s = sevIcons[ins.severity] || sevIcons.info;
    const drawerId = `insight-evidence-${idx}`;

    let evidenceHtml = '';
    if (ins.evidence && Object.keys(ins.evidence).length > 0) {
      evidenceHtml = Object.entries(ins.evidence).map(([k, v]) => `
        <div class="evidence-item">
          <span class="evidence-label">${escapeHtml(k.replace(/_/g, ' '))}</span>
          <span class="evidence-val">${typeof v === 'number' ? state.formatCurrency(v) : escapeHtml(v)}</span>
        </div>
      `).join('');
    }

    return `
      <div class="insight-card ${ins.severity || 'info'} stagger-in">
        <div class="insight-card-main">
          <div class="insight-content-wrap">
            <div class="insight-icon-box" style="background: ${s.bg}; color: ${s.color};">
              <i data-lucide="${s.icon}"></i>
            </div>
            <div>
              <div class="insight-title">
                ${escapeHtml(ins.title)}
                <span class="delta-badge neutral" style="font-size: 10.5px; padding: 1px 6px;">Score: ${ins.impact_score ? Math.round(ins.impact_score * 100) : 50}</span>
              </div>
              <div class="insight-summary">${escapeHtml(ins.summary)}</div>
            </div>
          </div>
          <div class="insight-actions">
            ${evidenceHtml ? `<button class="btn btn-secondary btn-sm evidence-toggle-btn" data-target="${drawerId}" style="padding: 4px 10px; font-size: 11.5px;">Why?</button>` : ''}
            <button class="btn btn-primary btn-sm insight-explore-btn" data-insight-id="${ins.id}" data-entity-id="${ins.entity_id || ''}" style="padding: 4px 10px; font-size: 11.5px;">Explore</button>
            <button class="btn btn-secondary btn-sm insight-dismiss-btn" data-key="${ins.insight_key || ins.id}" title="Dismiss insight" style="padding: 4px 8px; font-size: 11.5px;"><i data-lucide="x" style="width: 12px; height: 12px;"></i></button>
          </div>
        </div>
        ${evidenceHtml ? `<div id="${drawerId}" class="insight-evidence-drawer">${evidenceHtml}</div>` : ''}
      </div>
    `;
  }).join('');

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

  // Attach explore clicks
  container.querySelectorAll('.insight-explore-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const analyticsNav = document.querySelector('[data-page="analytics"]');
      if (analyticsNav) analyticsNav.click();
    });
  });
}

function renderKPIs(kpis, accounts = [], trend = null) {
  const incEl = document.getElementById('kpi-income-val');
  const expEl = document.getElementById('kpi-expense-val');
  const netValEl = document.getElementById('kpi-net-val');
  const savEl = document.getElementById('kpi-savings-val');
  const savPrevEl = document.getElementById('kpi-savings-prev');

  // Count-up animations for KPI figures
  animateCountUp(incEl, kpis.income, { formatter: v => state.formatCurrency(v) });
  animateCountUp(expEl, kpis.expense, { formatter: v => state.formatCurrency(v) });
  animateCountUp(netValEl, kpis.net_flow, { formatter: v => state.formatCurrency(v) });
  animateCountUp(savEl, kpis.savings_rate, { formatter: v => `${v.toFixed(1)}%` });
  savPrevEl.textContent = `Previous: ${kpis.prev_savings_rate}%`;

  // Income delta badge
  const incDelta = document.getElementById('kpi-income-delta');
  const incSign = kpis.income_delta_pct > 0 ? '+' : '';
  incDelta.textContent = `${incSign}${kpis.income_delta_pct}%`;
  incDelta.className = `delta-badge ${kpis.income_delta_pct > 0 ? 'positive' : (kpis.income_delta_pct < 0 ? 'negative' : 'neutral')}`;

  // Expense delta badge
  const expDelta = document.getElementById('kpi-expense-delta');
  const expSign = kpis.expense_delta_pct > 0 ? '+' : '';
  expDelta.textContent = `${expSign}${kpis.expense_delta_pct}%`;
  expDelta.className = `delta-badge ${kpis.expense_delta_pct > 0 ? 'negative' : (kpis.expense_delta_pct < 0 ? 'positive' : 'neutral')}`;

  // Net flow coloring
  if (kpis.net_flow > 0) {
    netValEl.style.color = 'var(--color-positive)';
  } else if (kpis.net_flow < 0) {
    netValEl.style.color = 'var(--color-negative)';
  } else {
    netValEl.style.color = 'var(--text-primary)';
  }

  // Net Cash Position (Liquid balances)
  const netCashEl = document.getElementById('kpi-net-cash-val');
  const netCashSub = document.getElementById('kpi-net-cash-sub');
  let netCash = 0;
  if (netCashEl) {
    const activeAccounts = (accounts && accounts.length > 0) ? accounts : (state.accounts || []);
    if (state.accountId) {
      const targetAcc = activeAccounts.find(a => a.id === state.accountId);
      netCash = targetAcc ? Number(targetAcc.current_balance || 0) : 0;
      if (netCashSub) {
        netCashSub.textContent = targetAcc ? `${targetAcc.name} balance` : 'Selected Account';
      }
    } else {
      netCash = activeAccounts.reduce((sum, a) => sum + Number(a.current_balance || 0), 0);
      if (netCashSub) {
        const count = activeAccounts.length;
        netCashSub.textContent = `${count} active account${count === 1 ? '' : 's'}`;
      }
    }
    animateCountUp(netCashEl, netCash, { formatter: v => state.formatCurrency(v) });
  }

  // Render Sparklines & Mini Gauges (P1.1, P1.2, P1.4)
  if (trend) {
    const incSparkEl = document.getElementById('kpi-income-sparkline');
    if (incSparkEl && trend.income) {
      renderSparkline(incSparkEl, trend.income, '#4DD5A5');
    }

    const expSparkEl = document.getElementById('kpi-expense-sparkline');
    if (expSparkEl && trend.expense) {
      renderSparkline(expSparkEl, trend.expense, '#FF6B8A');
    }

    const netSparkEl = document.getElementById('kpi-net-sparkline');
    if (netSparkEl && trend.income && trend.expense) {
      const netDaily = trend.income.map((inc, i) => inc - (trend.expense[i] || 0));
      renderSparkline(netSparkEl, netDaily, '#5B8CFF');
    }

    const cashSparkEl = document.getElementById('kpi-net-cash-sparkline');
    if (cashSparkEl && trend.income && trend.expense) {
      // Running net balance trajectory
      let running = netCash;
      const cum = trend.income.map((inc, i) => {
        running += (inc - (trend.expense[i] || 0));
        return running;
      });
      renderSparkline(cashSparkEl, cum, '#FFFFFF', { lightOnGradient: true });
    }
  }

  const savRadialEl = document.getElementById('kpi-savings-radial');
  if (savRadialEl) {
    renderRadialGauge(savRadialEl, kpis.savings_rate, '#C85AF4');
  }
}

function renderTrendChart(trend) {
  const chartDom = document.getElementById('trend-chart');
  if (!chartDom || !window.echarts) return;

  if (trendChartInstance) {
    try { trendChartInstance.dispose(); } catch (e) {}
  }
  trendChartInstance = window.echarts.init(chartDom);
  window.addEventListener('resize', () => trendChartInstance?.resize());

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params) => {
        let res = `<div style="font-weight:700; margin-bottom:6px; color: var(--text-primary);">Day ${params[0].axisValue}</div>`;
        params.forEach(p => {
          const val = state.privacyMode ? '••••••' : `$${Number(p.value).toLocaleString()}`;
          res += `<div style="display:flex; justify-content:space-between; gap:20px; font-size:12px; margin-top:2px;">
            <span>${p.marker} ${p.seriesName}:</span>
            <span style="font-weight:700; font-family:monospace;">${val}</span>
          </div>`;
        });
        return res;
      }
    },
    legend: {
      data: ['Income', 'Expense'],
      textStyle: { color: '#929CB6', fontSize: 12 },
      top: 0,
      right: 10
    },
    grid: GRID_TIGHT,
    xAxis: {
      type: 'category',
      data: trend.days,
      ...AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE
    },
    yAxis: {
      type: 'value',
      splitLine: SPLIT_LINE_STYLE,
      axisLabel: {
        ...AXIS_LABEL_STYLE,
        formatter: (val) => state.privacyMode ? '••' : `$${val >= 1000 ? (val / 1000).toFixed(0) + 'k' : val}`
      }
    },
    series: [
      {
        name: 'Income',
        type: 'line',
        smooth: 0.35,
        data: trend.income,
        itemStyle: { color: '#4DD5A5' },
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: verticalGradient('#4DD5A5', '#4DD5A5', 0.25, 0.0)
        }
      },
      {
        name: 'Expense',
        type: 'line',
        smooth: 0.35,
        data: trend.expense,
        itemStyle: { color: '#FF6B8A' },
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: verticalGradient('#FF6B8A', '#FF6B8A', 0.25, 0.0)
        }
      }
    ]
  };

  trendChartInstance.setOption(option, true);
}

function renderDonutChart(categories) {
  const chartDom = document.getElementById('donut-chart');
  if (!chartDom || !window.echarts) return;

  if (donutChartInstance) {
    try { donutChartInstance.dispose(); } catch (e) {}
  }
  donutChartInstance = window.echarts.init(chartDom);
  window.addEventListener('resize', () => donutChartInstance?.resize());

  const chartData = categories.map(c => ({
    name: c.name,
    value: c.amount,
    itemStyle: { color: c.color }
  }));

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'item',
      formatter: (p) => {
        const val = state.privacyMode ? '••••••' : `$${Number(p.value).toLocaleString()}`;
        return `<div style="font-size:12px;">${p.marker} <b>${p.name}</b><br/><span style="font-weight:700; font-family:monospace;">${val}</span> (${p.percent}%)</div>`;
      }
    },
    series: [
      {
        name: 'Expense by Category',
        type: 'pie',
        radius: ['52%', '78%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#171E33',
          borderWidth: 2
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 13,
            fontWeight: 'bold',
            color: '#F5F7FB',
            formatter: '{b}\n{d}%'
          }
        },
        data: chartData.length > 0 ? chartData : [{ name: 'No Expenses', value: 0, itemStyle: { color: '#333' } }]
      }
    ]
  };

  donutChartInstance.setOption(option, true);
}

function renderDailyChart(trend) {
  const chartDom = document.getElementById('daily-chart');
  if (!chartDom || !window.echarts) return;

  if (dailyChartInstance) {
    try { dailyChartInstance.dispose(); } catch (e) {}
  }
  dailyChartInstance = window.echarts.init(chartDom);
  window.addEventListener('resize', () => dailyChartInstance?.resize());

  // Find max spending value and day for peak highlight (P1.6)
  const maxSpend = Math.max(0, ...(trend.expense || []));

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (p) => {
        const val = state.privacyMode ? '••••••' : `$${Number(p[0].value).toLocaleString()}`;
        const isPeak = p[0].value === maxSpend && maxSpend > 0;
        return `<div style="font-size:12px;">Day ${p[0].axisValue}<br/>Daily Spend: <b style="font-family:monospace;">${val}</b>${isPeak ? ' <span class="delta-badge negative" style="font-size:9.5px; padding:1px 4px; margin-left:4px;">Peak Day</span>' : ''}</div>`;
      }
    },
    grid: GRID_TIGHT,
    xAxis: {
      type: 'category',
      data: trend.days,
      ...AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE
    },
    yAxis: {
      type: 'value',
      splitLine: SPLIT_LINE_STYLE,
      axisLabel: {
        ...AXIS_LABEL_STYLE,
        formatter: (v) => state.privacyMode ? '••' : `$${v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v}`
      }
    },
    series: [
      {
        name: 'Expense Bar',
        type: 'bar',
        data: (trend.expense || []).map(val => {
          const isPeak = val === maxSpend && maxSpend > 0;
          return {
            value: val,
            itemStyle: {
              color: isPeak ? '#FF6B8A' : verticalGradient('#C85AF4', '#5B8CFF', 1.0, 0.85),
              borderRadius: [4, 4, 0, 0]
            }
          };
        }),
        barMaxWidth: 18
      },
      {
        name: 'Spending Trend',
        type: 'line',
        smooth: 0.35,
        data: trend.expense,
        itemStyle: { color: '#27D5D5' },
        lineStyle: { width: 2.5, color: '#27D5D5' },
        showSymbol: false,
        markPoint: {
          data: [{ type: 'max', name: 'Peak' }],
          symbol: 'pin',
          symbolSize: 34,
          itemStyle: { color: '#FF6B8A' },
          label: {
            fontSize: 10,
            fontWeight: 'bold',
            color: '#FFFFFF',
            formatter: 'Peak'
          }
        }
      }
    ]
  };

  dailyChartInstance.setOption(option, true);
}

function renderRecentTransactions(transactions) {
  const tbody = document.getElementById('recent-tx-body');
  if (!tbody) return;

  if (!transactions || transactions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-muted); padding:20px;">No transactions recorded this month.</td></tr>';
    return;
  }

  tbody.innerHTML = transactions.map(tx => {
    const isIncome = tx.transaction_type === 'income';
    const sign = isIncome ? '+' : '-';
    const amtClass = isIncome ? 'income' : 'expense';
    const catColor = tx.category_color || '#5B8CFF';
    const merchantName = tx.merchant_name || tx.description || 'Transaction';
    const initials = getMerchantInitials(merchantName);

    return `
      <tr>
        <td style="color: var(--text-muted); font-size:12px;">${escapeHtml(tx.transaction_date.slice(5))}</td>
        <td>
          <div class="entity-cell">
            <div class="avatar-chip" style="background: ${catColor}22; color: ${catColor}; border: 1px solid ${catColor}44;" title="${escapeHtml(merchantName)}">
              ${escapeHtml(initials)}
            </div>
            <div>
              <div style="font-weight: 600; color: var(--text-primary); font-size: 13.5px;">${escapeHtml(merchantName)}</div>
              ${tx.account_name ? `<div style="font-size:11px; color:var(--text-muted);">${escapeHtml(tx.account_name)}</div>` : ''}
            </div>
          </div>
        </td>
        <td>
          <span class="tag-pill" style="background: ${catColor}20; color: ${catColor}; border: 1px solid ${catColor}40;">
            ${escapeHtml(tx.category_name || 'Uncategorized')}
          </span>
        </td>
        <td style="text-align: right;">
          <span class="amount-display ${amtClass} num-tabular">
            ${sign}${state.formatCurrency(tx.amount)}
          </span>
        </td>
      </tr>
    `;
  }).join('');
}
