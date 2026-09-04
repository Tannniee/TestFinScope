/**
 * FinScope BI Analytics Workspace Page
 * "What Changed?", Weekday Distributions, Cumulative Pacing & Merchant Leaderboards
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';

let varianceChart = null;
let weekdayChart = null;
let cumulativeChart = null;

export async function renderAnalyticsPage(container) {
  container.innerHTML = `
    <div class="analytics-view">
      <!-- Section 1: "What Changed?" Variance Analysis -->
      <div class="fin-card" style="margin-bottom: 24px;">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>"What Changed?" — Month-over-Month Variance</h3>
            <p>Identifies categories contributing most to changes in your expenses vs. previous month</p>
          </div>
        </div>

        <div class="grid-2col" style="grid-template-columns: 1.3fr 1fr; gap: 24px;">
          <div id="variance-chart" style="width: 100%; height: 320px;"></div>
          <div class="table-container" style="max-height: 320px; overflow-y: auto;">
            <table class="fin-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th style="text-align: right;">Current</th>
                  <th style="text-align: right;">Previous</th>
                  <th style="text-align: right;">Change</th>
                </tr>
              </thead>
              <tbody id="variance-table-body">
                <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Loading variance data...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Section 2: Spending by Weekday & Cumulative Pacing -->
      <div class="grid-2col" style="margin-bottom: 24px;">
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
              <h3>Cumulative Spending Pace</h3>
              <p>Current month vs. previous month spending trajectory</p>
            </div>
          </div>
          <div id="cumulative-chart" style="width: 100%; height: 260px;"></div>
        </div>
      </div>

      <!-- Section 3: Top Merchants & Expense Essentiality -->
      <div class="grid-2col" style="grid-template-columns: 1.2fr 1fr;">
        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Top Merchants & Payees</h3>
              <p>Highest spending destinations this month</p>
            </div>
          </div>
          <div id="merchants-container" style="display: flex; flex-direction: column; gap: 10px; max-height: 260px; overflow-y: auto;">
            <div style="text-align: center; color: var(--text-muted); padding: 20px;">Loading top merchants...</div>
          </div>
        </div>

        <div class="fin-card">
          <div class="card-header">
            <div class="card-title-wrap">
              <h3>Essential vs. Discretionary</h3>
              <p>Living essentials vs. lifestyle spending</p>
            </div>
          </div>
          <div id="essentiality-container" style="display: flex; flex-direction: column; gap: 16px; padding: 10px 0;">
            <div style="text-align: center; color: var(--text-muted); padding: 20px;">Loading breakdown...</div>
          </div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  await loadAnalytics();
}

async function loadAnalytics() {
  try {
    const [deepDive, summary] = await Promise.all([
      api.getAnalyticsDeepDive(state.month, state.accountId),
      api.getMonthSummary(state.month, state.accountId)
    ]);

    renderVarianceVisuals(deepDive.variance);
    renderWeekdayChart(deepDive.weekday);
    renderCumulativeChart(deepDive.cumulative);
    renderTopMerchants(deepDive.merchants);
    renderEssentiality(summary.essentiality);
  } catch (err) {
    console.error('Failed to load analytics deep dive:', err);
    showToast('Failed to load analytics', 'error');
  }
}

function renderVarianceVisuals(varianceList) {
  const tbody = document.getElementById('variance-table-body');
  const chartDom = document.getElementById('variance-chart');
  if (!tbody || !chartDom || !window.echarts) return;

  if (!varianceList || varianceList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-muted);">No variance data available.</td></tr>';
    return;
  }

  // 1. Render Table
  tbody.innerHTML = varianceList.map(v => {
    const sign = v.delta > 0 ? '+' : '';
    const colorClass = v.delta > 0 ? 'var(--color-negative)' : (v.delta < 0 ? 'var(--color-positive)' : 'var(--text-muted)');

    return `
      <tr>
        <td style="font-weight: 500;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${v.color}; margin-right:6px;"></span>
          ${v.name}
        </td>
        <td style="text-align: right;">${state.formatCurrency(v.current)}</td>
        <td style="text-align: right; color: var(--text-muted);">${state.formatCurrency(v.previous)}</td>
        <td style="text-align: right; font-weight: 600; color: ${colorClass};">
          ${sign}${state.formatCurrency(v.delta)} (${sign}${v.pct_change}%)
        </td>
      </tr>
    `;
  }).join('');

  // 2. Render Horizontal Variance Bar Chart
  if (!varianceChart) {
    varianceChart = window.echarts.init(chartDom);
    window.addEventListener('resize', () => varianceChart?.resize());
  }

  const topVariance = varianceList.slice(0, 7).reverse();
  const catNames = topVariance.map(v => v.name);
  const deltaValues = topVariance.map(v => v.delta);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB' },
      formatter: (p) => {
        const item = topVariance[p[0].dataIndex];
        const sign = item.delta > 0 ? '+' : '';
        const val = state.privacyMode ? '••••••' : `$${Math.abs(item.delta).toLocaleString()}`;
        return `<div><b>${item.name}</b><br/>Delta: <span style="color:${item.delta > 0 ? '#FF6B8A' : '#4DD5A5'}">${sign}${val} (${sign}${item.pct_change}%)</span></div>`;
      }
    },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
      axisLabel: {
        color: '#66708A',
        formatter: (v) => state.privacyMode ? '••' : `$${v}`
      }
    },
    yAxis: {
      type: 'category',
      data: catNames,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: '#F5F7FB', fontSize: 12 }
    },
    series: [
      {
        name: 'Delta',
        type: 'bar',
        data: deltaValues.map(d => ({
          value: d,
          itemStyle: {
            color: d > 0 ? '#FF6B8A' : '#4DD5A5',
            borderRadius: d > 0 ? [0, 4, 4, 0] : [4, 0, 0, 4]
          }
        }))
      }
    ]
  };

  varianceChart.setOption(option, true);
}

function renderWeekdayChart(weekdayData) {
  const chartDom = document.getElementById('weekday-chart');
  if (!chartDom || !window.echarts || !weekdayData) return;

  if (!weekdayChart) {
    weekdayChart = window.echarts.init(chartDom);
    window.addEventListener('resize', () => weekdayChart?.resize());
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB' },
      formatter: (p) => {
        const d = weekdayData[p[0].dataIndex];
        const avg = state.privacyMode ? '••••••' : `$${d.average}`;
        const total = state.privacyMode ? '••••••' : `$${d.total}`;
        return `<div><b>${d.day}</b><br/>Avg/Day: <b>${avg}</b><br/>Total: ${total} (${d.count} tx)</div>`;
      }
    },
    grid: { left: '3%', right: '3%', bottom: '5%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: weekdayData.map(w => w.day),
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: '#929CB6', fontSize: 12 }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
      axisLabel: {
        color: '#66708A',
        fontSize: 10,
        formatter: (v) => state.privacyMode ? '••' : `$${v}`
      }
    },
    series: [
      {
        name: 'Average Spend',
        type: 'bar',
        data: weekdayData.map(w => w.average),
        itemStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#5B8CFF' },
            { offset: 1, color: '#27D5D5' }
          ]),
          borderRadius: [4, 4, 0, 0]
        }
      }
    ]
  };

  weekdayChart.setOption(option, true);
}

function renderCumulativeChart(cumulativeData) {
  const chartDom = document.getElementById('cumulative-chart');
  if (!chartDom || !window.echarts || !cumulativeData) return;

  if (!cumulativeChart) {
    cumulativeChart = window.echarts.init(chartDom);
    window.addEventListener('resize', () => cumulativeChart?.resize());
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#171E33',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#F5F7FB' },
      formatter: (p) => {
        let res = `<div style="font-weight:600; margin-bottom:4px;">Day ${p[0].axisValue}</div>`;
        p.forEach(x => {
          const val = state.privacyMode ? '••••••' : `$${Number(x.value).toLocaleString()}`;
          res += `<div>${x.marker} ${x.seriesName}: <b>${val}</b></div>`;
        });
        return res;
      }
    },
    legend: {
      data: ['Current Month', 'Previous Month'],
      textStyle: { color: '#929CB6', fontSize: 11 },
      top: 0,
      right: 10
    },
    grid: { left: '3%', right: '3%', bottom: '5%', top: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: cumulativeData.days,
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
        name: 'Current Month',
        type: 'line',
        smooth: true,
        data: cumulativeData.current,
        itemStyle: { color: '#C85AF4' },
        lineStyle: { width: 3 }
      },
      {
        name: 'Previous Month',
        type: 'line',
        smooth: true,
        data: cumulativeData.previous,
        itemStyle: { color: '#5B8CFF' },
        lineStyle: { width: 2, type: 'dashed' }
      }
    ]
  };

  cumulativeChart.setOption(option, true);
}

function renderTopMerchants(merchants) {
  const container = document.getElementById('merchants-container');
  if (!container) return;

  if (!merchants || merchants.length === 0) {
    container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:20px;">No merchants recorded yet.</div>';
    return;
  }

  container.innerHTML = merchants.map(m => `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--bg-card-subtle); border-radius: var(--radius-md);">
      <div>
        <div style="font-weight: 600; font-size: 13.5px;">${m.merchant}</div>
        <div style="font-size: 11.5px; color: var(--text-muted);">${m.count} transactions</div>
      </div>
      <div style="font-weight: 700; color: var(--text-primary); font-size: 14px;">
        ${state.formatCurrency(m.total)}
      </div>
    </div>
  `).join('');
}

function renderEssentiality(ess) {
  const container = document.getElementById('essentiality-container');
  if (!container || !ess) return;

  container.innerHTML = `
    <div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
        <span style="color: var(--text-secondary);">Essential (Housing, Groceries, Transport)</span>
        <span style="font-weight: 600;">${state.formatCurrency(ess.essential)} (${ess.essential_pct}%)</span>
      </div>
      <div class="budget-progress-wrap" style="height: 10px;">
        <div class="budget-progress-fill on_track" style="width: ${ess.essential_pct}%;"></div>
      </div>
    </div>

    <div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
        <span style="color: var(--text-secondary);">Discretionary (Dining, Shopping, Leisure)</span>
        <span style="font-weight: 600;">${state.formatCurrency(ess.discretionary)} (${ess.discretionary_pct}%)</span>
      </div>
      <div class="budget-progress-wrap" style="height: 10px;">
        <div class="budget-progress-fill watch" style="width: ${ess.discretionary_pct}%;"></div>
      </div>
    </div>

    <div style="margin-top: 10px; padding: 12px; background: var(--bg-card-subtle); border-radius: var(--radius-md); font-size: 12px; color: var(--text-muted); line-height: 1.5;">
      A healthy financial rule of thumb recommends keeping essential living expenses within 50–60% of total spend.
    </div>
  `;
}
