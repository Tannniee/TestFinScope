/**
 * FinScope Financial Reports & Statements Page
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../utils.js';

export async function renderReportsPage(container) {
  container.innerHTML = `
    <div class="reports-view">
      <!-- Report Actions Header -->
      <div class="fin-card" style="margin-bottom: 24px; padding: 18px 22px;">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div>
            <h3 style="font-size: 16px; font-weight: 700;">Financial Statement & Export</h3>
            <p style="font-size: 12px; color: var(--text-muted);">Executive monthly performance summary</p>
          </div>

          <div style="display: flex; align-items: center; gap: 10px;">
            <button id="btn-export-csv" class="btn btn-secondary">
              <i data-lucide="download"></i> Export CSV
            </button>
            <button id="btn-print-report" class="btn btn-primary">
              <i data-lucide="printer"></i> Print / PDF
            </button>
          </div>
        </div>
      </div>

      <!-- Formal Statement Document -->
      <div class="fin-card" id="report-document" style="padding: 32px 36px; background-color: var(--bg-card); max-width: 900px; margin: 0 auto;">
        <!-- Header -->
        <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid var(--border-medium); padding-bottom: 24px; margin-bottom: 28px;">
          <div>
            <h2 style="font-size: 24px; font-weight: 800; color: var(--text-primary); letter-spacing: -0.02em;">FINANCIAL STATEMENT</h2>
            <div style="font-size: 13px; color: var(--accent-cyan); font-weight: 600; margin-top: 4px;">FinScope Personal Finance BI</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 15px; font-weight: 700; color: var(--text-primary);" id="report-period-label">September 2026</div>
            <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">Generated on ${new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</div>
          </div>
        </div>

        <!-- Executive Summary Cards -->
        <div class="grid-4col" style="margin-bottom: 32px;">
          <div style="padding: 16px; background: var(--bg-card-subtle); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Gross Income</div>
            <div id="rep-income" style="font-size: 20px; font-weight: 700; color: var(--color-positive); margin-top: 6px;">$0.00</div>
          </div>
          <div style="padding: 16px; background: var(--bg-card-subtle); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Total Expenses</div>
            <div id="rep-expense" style="font-size: 20px; font-weight: 700; color: var(--color-negative); margin-top: 6px;">$0.00</div>
          </div>
          <div style="padding: 16px; background: var(--bg-card-subtle); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Net Cash Flow</div>
            <div id="rep-net" style="font-size: 20px; font-weight: 700; margin-top: 6px;">$0.00</div>
          </div>
          <div style="padding: 16px; background: var(--bg-card-subtle); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Savings Rate</div>
            <div id="rep-savings" style="font-size: 20px; font-weight: 700; color: var(--accent-purple); margin-top: 6px;">0.0%</div>
          </div>
        </div>

        <!-- Category Breakdown Table -->
        <h4 style="font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); margin-bottom: 14px;">
          Expense Category Allocation
        </h4>
        <div class="table-container" style="margin-bottom: 32px;">
          <table class="fin-table" id="report-category-table">
            <thead>
              <tr>
                <th>Category</th>
                <th style="text-align: right;">Transactions</th>
                <th style="text-align: right;">Amount</th>
                <th style="text-align: right; width: 140px;">% Share</th>
              </tr>
            </thead>
            <tbody id="report-category-body">
              <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Loading statement details...</td></tr>
            </tbody>
          </table>
        </div>

        <!-- Essential vs Discretionary Section -->
        <div style="border-top: 1px solid var(--border-subtle); padding-top: 24px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--text-secondary);">
          <div>
            <span>Essential Living: <b id="rep-essential-val">$0.00</b></span>
            <span style="margin: 0 8px;">•</span>
            <span>Discretionary Lifestyle: <b id="rep-discretionary-val">$0.00</b></span>
          </div>
          <div style="font-size: 11.5px; color: var(--text-muted);">
            FinScope Private Offline BI Engine
          </div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  setupReportHandlers();
  await loadReportData();
}

function setupReportHandlers() {
  document.getElementById('btn-export-csv')?.addEventListener('click', async () => {
    const token = await api.getSessionToken();
    window.location.href = `/api/export_csv?token=${encodeURIComponent(token || '')}`;
    showToast('Exporting CSV statement...', 'info');
  });

  document.getElementById('btn-print-report')?.addEventListener('click', () => {
    window.print();
  });
}

async function loadReportData() {
  try {
    const summary = await api.getMonthSummary(state.month, state.accountId);

    document.getElementById('report-period-label').textContent = state.formatMonthLabel(state.month);
    document.getElementById('rep-income').textContent = state.formatCurrency(summary.kpis.income);
    document.getElementById('rep-expense').textContent = state.formatCurrency(summary.kpis.expense);
    
    const netEl = document.getElementById('rep-net');
    netEl.textContent = state.formatCurrency(summary.kpis.net_flow);
    netEl.style.color = summary.kpis.net_flow >= 0 ? 'var(--color-positive)' : 'var(--color-negative)';

    document.getElementById('rep-savings').textContent = `${summary.kpis.savings_rate}%`;
    document.getElementById('rep-essential-val').textContent = `${state.formatCurrency(summary.essentiality.essential)} (${summary.essentiality.essential_pct}%)`;
    document.getElementById('rep-discretionary-val').textContent = `${state.formatCurrency(summary.essentiality.discretionary)} (${summary.essentiality.discretionary_pct}%)`;

    // Render category table
    const tbody = document.getElementById('report-category-body');
    if (!summary.categories || summary.categories.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:20px;">No expense records for this statement period.</td></tr>';
      return;
    }

    tbody.innerHTML = summary.categories.map(c => `
      <tr>
        <td style="font-weight: 500;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${escapeHtml(c.color)}; margin-right:8px;"></span>
          ${escapeHtml(c.name)}
        </td>
        <td style="text-align: right; color: var(--text-muted);">${c.count}</td>
        <td style="text-align: right; font-weight: 600;">${state.formatCurrency(c.amount)}</td>
        <td style="text-align: right;">
          <div style="display:flex; align-items:center; justify-content:flex-end; gap:8px;">
            <div class="budget-progress-wrap" style="width: 60px; height: 6px;">
              <div class="budget-progress-fill" style="width: ${c.percentage}%; background-color: ${escapeHtml(c.color)};"></div>
            </div>
            <span style="font-weight:600; min-width:38px;">${c.percentage}%</span>
          </div>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Failed to load report:', err);
    showToast('Failed to load statement', 'error');
  }
}
