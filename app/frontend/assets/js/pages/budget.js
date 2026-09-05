/**
 * FinScope Budget System Page
 * Category budgets, pacing indicators, and month-end projections
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../utils.js';
import { renderRadialGauge } from '../charts/sparkline.js';

export async function renderBudgetPage(container) {
  container.innerHTML = `
    <div class="budget-view">
      <!-- Overall Budget Summary Banner -->
      <div class="fin-card" style="margin-bottom: 24px; padding: 22px;">
        <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 20px;">
          <div>
            <span style="font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); display: inline-flex; align-items: center; gap: 8px;">
              Monthly Budget Progress — ${state.formatMonthLabel(state.month)}
              ${state.accountId ? (() => {
                const acc = state.accounts.find(a => a.id === state.accountId);
                return `<span class="delta-badge neutral" style="font-size: 11px; text-transform: none; letter-spacing: normal;">Filtered: ${escapeHtml(acc ? acc.name : 'Account')}</span>`;
              })() : ''}
            </span>
            <div style="display: flex; align-items: baseline; gap: 12px; margin-top: 6px;">
              <span id="budget-summary-spent" class="num-tabular" style="font-size: 28px; font-weight: 700; color: var(--text-primary);">$0.00</span>
              <span style="font-size: 16px; color: var(--text-muted);">spent of <span id="budget-summary-total" class="num-tabular">$0.00</span> budget</span>
            </div>
          </div>

          <!-- Pacing Context with Radial Ring (P1.5) -->
          <div style="display: flex; align-items: center; gap: 22px;">
            <div id="budget-radial-gauge" style="width: 56px; height: 56px; min-width: 56px;"></div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Month Elapsed</div>
              <div id="budget-elapsed-pct" class="num-tabular" style="font-size: 18px; font-weight: 700; color: var(--text-secondary); margin-top: 2px;">0%</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Budget Consumed</div>
              <div id="budget-consumed-pct" class="num-tabular" style="font-size: 18px; font-weight: 700; margin-top: 2px;">0%</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Remaining</div>
              <div id="budget-remaining-val" class="num-tabular" style="font-size: 18px; font-weight: 700; color: var(--color-positive); margin-top: 2px;">$0.00</div>
            </div>
          </div>
        </div>

        <!-- Progress Bar -->
        <div class="budget-progress-wrap" style="height: 10px; margin-top: 20px;">
          <div id="budget-summary-fill" class="budget-progress-fill on_track" style="width: 0%;"></div>
        </div>
      </div>

      <!-- Category Budgets Grid -->
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
        <h3 style="font-size: 16px; font-weight: 700;">Category Budget Performance</h3>
        <span style="font-size: 12px; color: var(--text-muted);">Click "Set Budget" to adjust limits</span>
      </div>

      <div class="grid-2col" id="budget-cards-container">
        <div class="skeleton skeleton-card"></div>
        <div class="skeleton skeleton-card"></div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  await loadBudgetData();
}

async function loadBudgetData() {
  try {
    const data = await api.getMonthlyBudget(state.month, state.accountId);
    renderBudgetOverview(data);
  } catch (err) {
    console.error('Failed to load budget data:', err);
    showToast('Failed to load budget', 'error');
  }
}

function renderBudgetOverview(data) {
  const { summary, elapsed_pct, items } = data;

  // Header stats
  document.getElementById('budget-summary-spent').textContent = state.formatCurrency(summary.total_spent);
  document.getElementById('budget-summary-total').textContent = state.formatCurrency(summary.total_budget);
  document.getElementById('budget-elapsed-pct').textContent = `${elapsed_pct}%`;
  
  const consumedEl = document.getElementById('budget-consumed-pct');
  consumedEl.textContent = `${summary.consumed_pct}%`;
  consumedEl.style.color = summary.consumed_pct > 100 ? 'var(--color-negative)' : (summary.consumed_pct > elapsed_pct + 15 ? 'var(--color-warning)' : 'var(--color-positive)');

  const remainingEl = document.getElementById('budget-remaining-val');
  remainingEl.textContent = state.formatCurrency(summary.remaining);
  remainingEl.style.color = summary.remaining < 0 ? 'var(--color-negative)' : 'var(--color-positive)';

  const fillEl = document.getElementById('budget-summary-fill');
  const fillWidth = Math.min(summary.consumed_pct, 100);
  fillEl.style.width = `${fillWidth}%`;
  fillEl.className = `budget-progress-fill ${summary.is_over ? 'over_budget' : (summary.consumed_pct > elapsed_pct + 15 ? 'watch' : 'on_track')}`;

  // Render Radial Gauge Ring (P1.5)
  const radialEl = document.getElementById('budget-radial-gauge');
  if (radialEl) {
    const ringColor = summary.consumed_pct > 100 ? '#FF6B8A' : (summary.consumed_pct > elapsed_pct + 15 ? '#FFCC66' : '#4DD5A5');
    renderRadialGauge(radialEl, summary.consumed_pct, ringColor, { radius: ['70%', '96%'] });
  }

  // Render Category Cards
  const container = document.getElementById('budget-cards-container');
  if (!container) return;

  if (!items || items.length === 0) {
    container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;">No expense categories found.</div>';
    return;
  }

  container.innerHTML = items.map(cat => {
    const hasBudget = cat.budget > 0;
    const barWidth = Math.min(cat.consumed_pct || 0, 100);
    const catColor = cat.category_color || '#5B8CFF';

    let statusBadgeClass = 'neutral';
    if (cat.status === 'on_track') statusBadgeClass = 'positive';
    if (cat.status === 'watch') statusBadgeClass = 'warning';
    if (cat.status === 'over_budget') statusBadgeClass = 'negative';

    return `
      <div class="fin-card" style="padding: 18px 20px;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="width: 34px; height: 34px; border-radius: var(--radius-sm); background: ${catColor}20; color: ${catColor}; display: flex; align-items: center; justify-content: center;">
              <i data-lucide="${cat.category_icon || 'tag'}"></i>
            </div>
            <div>
              <div style="font-weight: 600; font-size: 14px;">${escapeHtml(cat.category_name)}</div>
              <div style="font-size: 12px; color: var(--text-muted);">
                ${hasBudget ? `${state.formatCurrency(cat.spent)} of ${state.formatCurrency(cat.budget)}` : `Spent: ${state.formatCurrency(cat.spent)}`}
              </div>
            </div>
          </div>

          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="delta-badge ${statusBadgeClass}">${cat.status_label}</span>
            <button class="btn btn-secondary btn-sm btn-edit-budget" data-id="${cat.category_id}" data-name="${escapeHtml(cat.category_name)}" data-amount="${cat.budget || ''}">
              ${hasBudget ? 'Edit' : 'Set'}
            </button>
          </div>
        </div>

        ${hasBudget ? `
          <div class="budget-progress-wrap" style="margin: 14px 0 10px 0;">
            <div class="budget-progress-fill ${cat.status}" style="width: ${barWidth}%;"></div>
          </div>

          <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-muted);">
            <span>${cat.consumed_pct}% consumed</span>
            <span>Projected: <b>${state.formatCurrency(cat.projected)}</b></span>
          </div>
        ` : `
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 10px; font-style: italic;">
            No budget limit set. Click "Set" to set a monthly target.
          </div>
        `}
      </div>
    `;
  }).join('');

  if (window.lucide) window.lucide.createIcons({ root: container });

  // Add click handlers for Edit/Set budget buttons
  container.querySelectorAll('.btn-edit-budget').forEach(btn => {
    btn.addEventListener('click', () => {
      const catId = parseInt(btn.dataset.id);
      const catName = btn.dataset.name;
      const amount = parseFloat(btn.dataset.amount) || 0;
      modals.openBudgetModal(catId, catName, amount);
    });
  });
}
