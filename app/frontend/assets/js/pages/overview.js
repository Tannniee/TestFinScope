/**
 * FinScope Overview Dashboard Page
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';

let trendChartInstance = null;
let donutChartInstance = null;
let dailyChartInstance = null;

export async function renderOverviewPage(container) {
  container.innerHTML = `
    <div class="overview-view">
      <!-- KPI Cards Row -->
      <div class="grid-4col" id="kpi-row" style="margin-bottom: 24px;">
        <div class="kpi-card" id="kpi-income">
          <div class="kpi-header">
            <span class="kpi-label">Total Income</span>
            <div class="kpi-icon" style="background: rgba(77, 213, 165, 0.15); color: #4DD5A5;">
              <i data-lucide="arrow-down-left"></i>
            </div>
          </div>
          <div class="kpi-value amount-value" id="kpi-income-val">$0.00</div>
          <div class="kpi-footer">
            <span class="delta-badge neutral" id="kpi-income-delta">0%</span>
            <span>vs previous month</span>
          </div>
        </div>

        <div class="kpi-card" id="kpi-expense">
          <div class="kpi-header">
            <span class="kpi-label">Total Expense</span>
            <div class="kpi-icon" style="background: rgba(255, 107, 138, 0.15); color: #FF6B8A;">
              <i data-lucide="arrow-up-right"></i>
            </div>
          </div>
          <div class="kpi-value amount-value" id="kpi-expense-val">$0.00</div>
          <div class="kpi-footer">
            <span class="delta-badge neutral" id="kpi-expense-delta">0%</span>
            <span>vs previous month</span>
          </div>
        </div>

        <div class="kpi-card" id="kpi-net">
          <div class="kpi-header">
            <span class="kpi-label">Net Cash Flow</span>
            <div class="kpi-icon" style="background: rgba(91, 140, 255, 0.15); color: #5B8CFF;">
              <i data-lucide="wallet"></i>
            </div>
          </div>
          <div class="kpi-value amount-value" id="kpi-net-val">$0.00</div>
          <div class="kpi-footer">
            <span id="kpi-net-status" style="color: var(--text-secondary);">Income - Expenses</span>
          </div>
        </div>

        <div class="kpi-card" id="kpi-savings">
          <div class="kpi-header">
            <span class="kpi-label">Savings Rate</span>
            <div class="kpi-icon" style="background: rgba(200, 90, 244, 0.15); color: #C85AF4;">
              <i data-lucide="pie-chart"></i>
            </div>
          </div>
          <div class="kpi-value" id="kpi-savings-val">0.0%</div>
          <div class="kpi-footer">
            <span id="kpi-savings-prev">Previous: 0.0%</span>
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
              <p>Expense intensity per day of the month</p>
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
                <tr><td colspan="4" style="text-align:center; color: var(--text-muted);">Loading transactions...</td></tr>
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
    const [summary, recentTxs, insightsData] = await Promise.all([
      api.getMonthSummary(state.month, state.accountId),
      api.getTransactions({ month: state.month, limit: 6 }),
      api.getRankedInsights(state.month, state.accountId, 4)
    ]);

    renderKPIs(summary.kpis);
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
          <span class="evidence-label">${k.replace(/_/g, ' ')}</span>
          <span class="evidence-val">${typeof v === 'number' ? state.formatCurrency(v) : v}</span>
        </div>
      `).join('');
    }

    return `
      <div class="insight-card ${ins.severity || 'info'}">
        <div class="insight-card-main">
          <div class="insight-content-wrap">
            <div class="insight-icon-box" style="background: ${s.bg}; color: ${s.color};">
              <i data-lucide="${s.icon}"></i>
            </div>
            <div>
              <div class="insight-title">
                ${ins.title}
                <span class="delta-badge neutral" style="font-size: 10.5px; padding: 1px 6px;">Score: ${ins.impact_score ? Math.round(ins.impact_score * 100) : 50}</span>
              </div>
              <div class="insight-summary">${ins.summary}</div>
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
      // Navigate to Analytics page
      const analyticsNav = document.querySelector('[data-page="analytics"]');
      if (analyticsNav) analyticsNav.click();
    });
  });
}

function renderKPIs(kpis) {
  document.getElementById('kpi-income-val').textContent = state.formatCurrency(kpis.income);
  document.getElementById('kpi-expense-val').textContent = state.formatCurrency(kpis.expense);
  document.getElementById('kpi-net-val').textContent = state.formatCurrency(kpis.net_flow);
  document.getElementById('kpi-savings-val').textContent = `${kpis.savings_rate}%`;
  document.getElementById('kpi-savings-prev').textContent = `Previous: ${kpis.prev_savings_rate}%`;

  // Income delta badge
  const incDelta = document.getElementById('kpi-income-delta');
  const incSign = kpis.income_delta_pct > 0 ? '+' : '';
  incDelta.textContent = `${incSign}${kpis.income_delta_pct}%`;
  incDelta.className = `delta-badge ${kpis.income_delta_pct > 0 ? 'positive' : (kpis.income_delta_pct < 0 ? 'negative' : 'neutral')}`;

  // Expense delta badge
  const expDelta = document.getElementById('kpi-expense-delta');
  const expSign = kpis.expense_delta_pct > 0 ? '+' : '';
  expDelta.textContent = `${expSign}${kpis.expense_delta_pct}%`;
  // For expense, higher is negative (more spend)
  expDelta.className = `delta-badge ${kpis.expense_delta_pct > 0 ? 'negative' : (kpis.expense_delta_pct < 0 ? 'positive' : 'neutral')}`;

  // Net flow coloring
  const netValEl = document.getElementById('kpi-net-val');
  if (kpis.net_flow > 0) {
    netValEl.style.color = 'var(--color-positive)';
  } else if (kpis.net_flow < 0) {
    netValEl.style.color = 'var(--color-negative)';
  } else {
    netValEl.style.color = 'var(--text-primary)';
  }
}

function renderTrendChart(trend) {
  const chartDom = document.getElementById('trend-chart');
  if (!chartDom || !window.echarts) return;

  if (!trendChartInstance) {
    trendChartInstance = window.echarts.init(chartDom);
    window.addEventListener('resize', () => trendChartInstance?.resize());
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB', fontSize: 12 },
      formatter: (params) => {
        let res = `<div style="font-weight:600; margin-bottom:4px;">Day ${params[0].axisValue}</div>`;
        params.forEach(p => {
          const val = state.privacyMode ? '••••••' : `$${Number(p.value).toLocaleString()}`;
          res += `<div style="display:flex; justify-content:space-between; gap:16px;">
            <span>${p.marker} ${p.seriesName}:</span>
            <span style="font-weight:600;">${val}</span>
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
    grid: {
      left: '3%',
      right: '3%',
      bottom: '3%',
      top: '14%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: trend.days,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: '#66708A', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
      axisLabel: {
        color: '#66708A',
        fontSize: 11,
        formatter: (val) => state.privacyMode ? '••' : `$${val >= 1000 ? (val / 1000).toFixed(0) + 'k' : val}`
      }
    },
    series: [
      {
        name: 'Income',
        type: 'line',
        smooth: true,
        data: trend.income,
        itemStyle: { color: '#4DD5A5' },
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(77, 213, 165, 0.25)' },
            { offset: 1, color: 'rgba(77, 213, 165, 0.0)' }
          ])
        }
      },
      {
        name: 'Expense',
        type: 'line',
        smooth: true,
        data: trend.expense,
        itemStyle: { color: '#FF6B8A' },
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(255, 107, 138, 0.25)' },
            { offset: 1, color: 'rgba(255, 107, 138, 0.0)' }
          ])
        }
      }
    ]
  };

  trendChartInstance.setOption(option, true);
}

function renderDonutChart(categories) {
  const chartDom = document.getElementById('donut-chart');
  if (!chartDom || !window.echarts) return;

  if (!donutChartInstance) {
    donutChartInstance = window.echarts.init(chartDom);
    window.addEventListener('resize', () => donutChartInstance?.resize());
  }

  const chartData = categories.map(c => ({
    name: c.name,
    value: c.amount,
    itemStyle: { color: c.color }
  }));

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB', fontSize: 12 },
      formatter: (p) => {
        const val = state.privacyMode ? '••••••' : `$${Number(p.value).toLocaleString()}`;
        return `<div>${p.marker} <b>${p.name}</b><br/>${val} (${p.percent}%)</div>`;
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

  if (!dailyChartInstance) {
    dailyChartInstance = window.echarts.init(chartDom);
    window.addEventListener('resize', () => dailyChartInstance?.resize());
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB' },
      formatter: (p) => {
        const val = state.privacyMode ? '••••••' : `$${Number(p[0].value).toLocaleString()}`;
        return `<div>Day ${p[0].axisValue}<br/>Expense: <b>${val}</b></div>`;
      }
    },
    grid: {
      left: '3%',
      right: '3%',
      bottom: '3%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: trend.days,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: '#66708A', fontSize: 10 }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
      axisLabel: {
        color: '#66708A',
        fontSize: 10,
        formatter: (v) => state.privacyMode ? '••' : `$${v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v}`
      }
    },
    series: [
      {
        name: 'Expense',
        type: 'bar',
        data: trend.expense,
        itemStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#C85AF4' },
            { offset: 1, color: '#5B8CFF' }
          ]),
          borderRadius: [4, 4, 0, 0]
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

    return `
      <tr>
        <td style="color: var(--text-muted); font-size:12px;">${tx.transaction_date.slice(5)}</td>
        <td>
          <div style="font-weight: 500;">${tx.merchant_name || tx.description || 'Transaction'}</div>
          ${tx.account_name ? `<div style="font-size:11px; color:var(--text-muted);">${tx.account_name}</div>` : ''}
        </td>
        <td>
          <span class="tag-pill" style="background: ${catColor}20; color: ${catColor}; border: 1px solid ${catColor}40;">
            ${tx.category_name || 'Uncategorized'}
          </span>
        </td>
        <td style="text-align: right;">
          <span class="amount-display ${amtClass}">
            ${sign}${state.formatCurrency(tx.amount)}
          </span>
        </td>
      </tr>
    `;
  }).join('');
}
