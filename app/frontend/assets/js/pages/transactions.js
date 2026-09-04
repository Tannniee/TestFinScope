/**
 * FinScope Transactions Management Page
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';

let currentOffset = 0;
const PAGE_SIZE = 25;
let activeFilters = {
  search: '',
  category_id: null,
  account_id: null,
  transaction_type: null,
  essentiality: null
};

export async function renderTransactionsPage(container) {
  container.innerHTML = `
    <div class="transactions-view">
      <!-- Filter Bar -->
      <div class="fin-card" style="margin-bottom: 20px; padding: 18px 22px;">
        <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px;">
          <!-- Left: Search & Dropdowns -->
          <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 12px; flex: 1;">
            <div style="position: relative; min-width: 220px;">
              <input type="text" id="filter-search" class="form-input" placeholder="Search merchant, description..." style="width: 100%; padding-left: 36px;" />
              <i data-lucide="search" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--text-muted);"></i>
            </div>

            <select id="filter-category" class="form-select" style="min-width: 150px;">
              <option value="">All Categories</option>
              ${state.categories.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
            </select>

            <select id="filter-account" class="form-select" style="min-width: 150px;">
              <option value="">All Accounts</option>
              ${state.accounts.map(a => `<option value="${a.id}">${a.name}</option>`).join('')}
            </select>

            <select id="filter-type" class="form-select" style="min-width: 120px;">
              <option value="">All Types</option>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
              <option value="transfer">Transfer</option>
            </select>

            <select id="filter-essentiality" class="form-select" style="min-width: 140px;">
              <option value="">All Essentiality</option>
              <option value="essential">Essential</option>
              <option value="discretionary">Discretionary</option>
              <option value="savings">Savings</option>
            </select>

            <button id="btn-reset-filters" class="btn btn-secondary btn-sm" title="Clear filters">
              <i data-lucide="rotate-ccw"></i> Reset
            </button>
          </div>

          <!-- Right: Action Button -->
          <div>
            <button id="btn-add-tx" class="btn btn-primary">
              <i data-lucide="plus"></i> Add Transaction
            </button>
          </div>
        </div>
      </div>

      <!-- Transactions Table Card -->
      <div class="fin-card">
        <div class="card-header" style="margin-bottom: 12px;">
          <div class="card-title-wrap">
            <h3>Transaction Records</h3>
            <p id="tx-results-count">Loading transactions...</p>
          </div>
          <!-- Pagination Controls -->
          <div style="display: flex; align-items: center; gap: 8px;">
            <button id="btn-prev-page" class="btn btn-secondary btn-sm" disabled>
              <i data-lucide="chevron-left"></i> Previous
            </button>
            <span id="page-indicator" style="font-size: 12px; color: var(--text-muted); padding: 0 6px;">Page 1</span>
            <button id="btn-next-page" class="btn btn-secondary btn-sm" disabled>
              Next <i data-lucide="chevron-right"></i>
            </button>
          </div>
        </div>

        <div class="table-container">
          <table class="fin-table" id="transactions-full-table">
            <thead>
              <tr>
                <th style="width: 110px;">Date</th>
                <th>Merchant / Details</th>
                <th>Category</th>
                <th>Account</th>
                <th>Essentiality</th>
                <th style="text-align: right;">Amount</th>
                <th style="text-align: right; width: 110px;">Actions</th>
              </tr>
            </thead>
            <tbody id="transactions-full-body">
              <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 30px;">Loading...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  setupEventListeners();
  await loadTransactions();
}

function setupEventListeners() {
  document.getElementById('btn-add-tx')?.addEventListener('click', () => {
    modals.openTransactionModal();
  });

  // Filters
  const searchInput = document.getElementById('filter-search');
  let debounceTimeout = null;
  searchInput?.addEventListener('input', (e) => {
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      activeFilters.search = e.target.value.trim();
      currentOffset = 0;
      loadTransactions();
    }, 300);
  });

  document.getElementById('filter-category')?.addEventListener('change', (e) => {
    activeFilters.category_id = e.target.value ? parseInt(e.target.value) : null;
    currentOffset = 0;
    loadTransactions();
  });

  document.getElementById('filter-account')?.addEventListener('change', (e) => {
    activeFilters.account_id = e.target.value ? parseInt(e.target.value) : null;
    currentOffset = 0;
    loadTransactions();
  });

  document.getElementById('filter-type')?.addEventListener('change', (e) => {
    activeFilters.transaction_type = e.target.value || null;
    currentOffset = 0;
    loadTransactions();
  });

  document.getElementById('filter-essentiality')?.addEventListener('change', (e) => {
    activeFilters.essentiality = e.target.value || null;
    currentOffset = 0;
    loadTransactions();
  });

  document.getElementById('btn-reset-filters')?.addEventListener('click', () => {
    activeFilters = { search: '', category_id: null, account_id: null, transaction_type: null, essentiality: null };
    document.getElementById('filter-search').value = '';
    document.getElementById('filter-category').value = '';
    document.getElementById('filter-account').value = '';
    document.getElementById('filter-type').value = '';
    document.getElementById('filter-essentiality').value = '';
    currentOffset = 0;
    loadTransactions();
  });

  // Pagination
  document.getElementById('btn-prev-page')?.addEventListener('click', () => {
    if (currentOffset >= PAGE_SIZE) {
      currentOffset -= PAGE_SIZE;
      loadTransactions();
    }
  });

  document.getElementById('btn-next-page')?.addEventListener('click', () => {
    currentOffset += PAGE_SIZE;
    loadTransactions();
  });
}

async function loadTransactions() {
  try {
    const params = {
      month: state.month,
      account_id: activeFilters.account_id || state.accountId,
      category_id: activeFilters.category_id,
      transaction_type: activeFilters.transaction_type,
      essentiality: activeFilters.essentiality,
      search: activeFilters.search,
      limit: PAGE_SIZE,
      offset: currentOffset
    };

    const res = await api.getTransactions(params);
    renderTable(res.items, res.total);
  } catch (err) {
    console.error('Failed to load transactions:', err);
    showToast('Failed to load transactions', 'error');
  }
}

function renderTable(items, total) {
  const tbody = document.getElementById('transactions-full-body');
  const countLabel = document.getElementById('tx-results-count');
  const pageIndicator = document.getElementById('page-indicator');
  const prevBtn = document.getElementById('btn-prev-page');
  const nextBtn = document.getElementById('btn-next-page');

  if (!tbody) return;

  // Update counter & pagination
  const startIdx = total === 0 ? 0 : currentOffset + 1;
  const endIdx = Math.min(currentOffset + PAGE_SIZE, total);
  countLabel.textContent = `Showing ${startIdx}–${endIdx} of ${total} transactions for ${state.formatMonthLabel(state.month)}`;

  const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;
  pageIndicator.textContent = `Page ${currentPage} of ${totalPages}`;
  prevBtn.disabled = currentOffset <= 0;
  nextBtn.disabled = currentOffset + PAGE_SIZE >= total;

  if (!items || items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 40px;">
          <div style="font-size: 15px; margin-bottom: 6px;">No transactions found</div>
          <div style="font-size: 12px;">Try adjusting your filters or click "+ Add Transaction"</div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = items.map(tx => {
    const isIncome = tx.transaction_type === 'income';
    const sign = isIncome ? '+' : '-';
    const amtClass = isIncome ? 'income' : 'expense';
    const catColor = tx.category_color || '#5B8CFF';

    return `
      <tr data-id="${tx.id}">
        <td>
          <div style="font-weight: 500;">${tx.transaction_date}</div>
          <div style="font-size: 11px; color: var(--text-muted);">${tx.transaction_time || ''}</div>
        </td>
        <td>
          <div style="font-weight: 600; color: var(--text-primary);">${tx.merchant_name || tx.description || 'Transaction'}</div>
          ${tx.note ? `<div style="font-size: 11.5px; color: var(--text-secondary);">${tx.note}</div>` : ''}
        </td>
        <td>
          <span class="tag-pill" style="background: ${catColor}20; color: ${catColor}; border: 1px solid ${catColor}40;">
            ${tx.category_name || 'Uncategorized'}
          </span>
        </td>
        <td>
          <span style="font-size: 12.5px; color: var(--text-secondary);">${tx.account_name || 'Everyday'}</span>
        </td>
        <td>
          <span class="tag-pill" style="background: rgba(255,255,255,0.06); color: var(--text-secondary); text-transform: capitalize;">
            ${tx.essentiality || 'discretionary'}
          </span>
        </td>
        <td style="text-align: right;">
          <span class="amount-display ${amtClass}" style="font-size: 14px;">
            ${sign}${state.formatCurrency(tx.amount)}
          </span>
        </td>
        <td style="text-align: right;">
          <div style="display: inline-flex; align-items: center; gap: 4px;">
            <button class="btn btn-secondary btn-icon btn-sm action-edit" data-id="${tx.id}" title="Edit">
              <i data-lucide="edit-2" style="width: 14px; height: 14px;"></i>
            </button>
            <button class="btn btn-secondary btn-icon btn-sm action-duplicate" data-id="${tx.id}" title="Duplicate">
              <i data-lucide="copy" style="width: 14px; height: 14px;"></i>
            </button>
            <button class="btn btn-danger btn-icon btn-sm action-delete" data-id="${tx.id}" title="Delete">
              <i data-lucide="trash-2" style="width: 14px; height: 14px;"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  if (window.lucide) window.lucide.createIcons({ root: tbody });

  // Attach row action listeners
  tbody.querySelectorAll('.action-edit').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tx = items.find(t => t.id === parseInt(btn.dataset.id));
      if (tx) modals.openTransactionModal(tx);
    });
  });

  tbody.querySelectorAll('.action-duplicate').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api.duplicateTransaction(parseInt(btn.dataset.id));
        showToast('Transaction duplicated', 'success');
        state.notify({ type: 'data_changed' });
      } catch (err) {
        showToast(`Duplicate failed: ${err.message}`, 'error');
      }
    });
  });

  tbody.querySelectorAll('.action-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (confirm('Are you sure you want to delete this transaction?')) {
        try {
          await api.deleteTransaction(parseInt(btn.dataset.id));
          showToast('Transaction deleted', 'success');
          state.notify({ type: 'data_changed' });
        } catch (err) {
          showToast(`Delete failed: ${err.message}`, 'error');
        }
      }
    });
  });
}
