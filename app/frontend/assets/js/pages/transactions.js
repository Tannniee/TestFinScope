/**
 * FinScope Transactions Management Page
 * With Review Queue, Quick Refund Linking, and Non-blocking 5s Undo Delete
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';
import { escapeHtml, getMerchantInitials } from '../utils.js';

let currentOffset = 0;
const PAGE_SIZE = 25;
let isReviewQueueActive = false;
let reviewQueueCount = 0;

let activeFilters = {
  search: '',
  category_id: null,
  account_id: null,
  transaction_type: null,
  essentiality: null
};

export function resetTransactionPageState() {
  currentOffset = 0;
  isReviewQueueActive = false;
  activeFilters = {
    search: '',
    category_id: null,
    account_id: null,
    transaction_type: null,
    essentiality: null
  };
}

export async function renderTransactionsPage(container, context = {}) {
  resetTransactionPageState();
  if (context.registerCleanup) {
    context.registerCleanup(() => {
      resetTransactionPageState();
    });
  }
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
              ${state.categories.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('')}
            </select>

            <select id="filter-account" class="form-select" style="min-width: 150px;">
              <option value="" ${!state.accountId ? 'selected' : ''}>All Accounts</option>
              ${state.accounts.map(a => `<option value="${escapeHtml(a.id)}" ${state.accountId === a.id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}
            </select>

            <select id="filter-type" class="form-select" style="min-width: 120px;">
              <option value="">All Types</option>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
              <option value="transfer">Transfer</option>
              <option value="refund">Refund</option>
            </select>

            <select id="filter-essentiality" class="form-select" style="min-width: 140px;">
              <option value="">All Essentiality</option>
              <option value="essential">Essential</option>
              <option value="discretionary">Discretionary</option>
              <option value="savings">Savings</option>
            </select>

            <button id="btn-review-queue" class="btn-review-queue" title="View transactions requiring categorization review">
              <i data-lucide="help-circle" style="width: 15px; height: 15px;"></i>
              <span>Review Queue</span>
              <span id="review-queue-badge" class="badge-count" style="display: none;">0</span>
            </button>

            <button id="btn-reset-filters" class="btn btn-secondary btn-sm" title="Clear filters">
              <i data-lucide="rotate-ccw"></i> Reset
            </button>
          </div>

          <!-- Right: Action Button -->
          <div>
            <button id="btn-add-tx" class="btn btn-primary" title="Record transaction (Shortcut: Ctrl+N)">
              <i data-lucide="plus"></i> Add Transaction
            </button>
          </div>
        </div>
      </div>

      <!-- Transactions Table Card -->
      <div class="fin-card">
        <div class="card-header" style="margin-bottom: 12px;">
          <div class="card-title-wrap">
            <h3 id="tx-table-title">Transaction Records</h3>
            <p id="tx-results-count">Loading transactions...</p>
          </div>
          <!-- Pagination Controls -->
          <div id="tx-pagination-wrap" style="display: flex; align-items: center; gap: 8px;">
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
                <th style="text-align: right; width: 140px;">Actions</th>
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
  await updateReviewQueueBadge();
  await loadTransactions();
}

async function updateReviewQueueBadge() {
  try {
    const queue = await api.getReviewQueue(50, 0, state.accountId);
    reviewQueueCount = queue?.total ?? (Array.isArray(queue) ? queue.length : queue?.items?.length || 0);
    const badge = document.getElementById('review-queue-badge');
    if (badge) {
      if (reviewQueueCount > 0) {
        badge.textContent = reviewQueueCount;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (err) {
    console.warn('Failed to fetch review queue count:', err);
  }
}

function setupEventListeners() {
  document.getElementById('btn-add-tx')?.addEventListener('click', () => {
    modals.openTransactionModal();
  });

  // Review Queue Toggle Button
  const reviewBtn = document.getElementById('btn-review-queue');
  reviewBtn?.addEventListener('click', () => {
    isReviewQueueActive = !isReviewQueueActive;
    reviewBtn.classList.toggle('active', isReviewQueueActive);
    currentOffset = 0;
    const pagination = document.getElementById('tx-pagination-wrap');
    const title = document.getElementById('tx-table-title');

    if (isReviewQueueActive) {
      if (pagination) pagination.style.display = 'none';
      if (title) title.textContent = 'Review Queue (Unconfirmed / Needs Attention)';
      loadReviewQueueItems();
    } else {
      if (pagination) pagination.style.display = 'flex';
      if (title) title.textContent = 'Transaction Records';
      loadTransactions();
    }
  });

  // Search filter
  const searchInput = document.getElementById('filter-search');
  let debounceTimeout = null;
  searchInput?.addEventListener('input', (e) => {
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      activeFilters.search = e.target.value.trim();
      currentOffset = 0;
      if (!isReviewQueueActive) loadTransactions();
    }, 300);
  });

  document.getElementById('filter-category')?.addEventListener('change', (e) => {
    activeFilters.category_id = e.target.value ? parseInt(e.target.value) : null;
    currentOffset = 0;
    if (!isReviewQueueActive) loadTransactions();
  });

  document.getElementById('filter-account')?.addEventListener('change', (e) => {
    activeFilters.account_id = e.target.value ? parseInt(e.target.value) : 'ALL';
    currentOffset = 0;
    if (!isReviewQueueActive) loadTransactions();
  });

  document.getElementById('filter-type')?.addEventListener('change', (e) => {
    activeFilters.transaction_type = e.target.value || null;
    currentOffset = 0;
    if (!isReviewQueueActive) loadTransactions();
  });

  document.getElementById('filter-essentiality')?.addEventListener('change', (e) => {
    activeFilters.essentiality = e.target.value || null;
    currentOffset = 0;
    if (!isReviewQueueActive) loadTransactions();
  });

  document.getElementById('btn-reset-filters')?.addEventListener('click', () => {
    activeFilters = { search: '', category_id: null, account_id: state.accountId || null, transaction_type: null, essentiality: null };
    const searchEl = document.getElementById('filter-search');
    const catEl = document.getElementById('filter-category');
    const accEl = document.getElementById('filter-account');
    const typeEl = document.getElementById('filter-type');
    const essEl = document.getElementById('filter-essentiality');

    if (searchEl) searchEl.value = '';
    if (catEl) catEl.value = '';
    if (accEl) accEl.value = state.accountId || '';
    if (typeEl) typeEl.value = '';
    if (essEl) essEl.value = '';

    isReviewQueueActive = false;
    document.getElementById('btn-review-queue')?.classList.remove('active');
    const paginationWrap = document.getElementById('tx-pagination-wrap');
    if (paginationWrap) paginationWrap.style.display = 'flex';
    const titleEl = document.getElementById('tx-table-title');
    if (titleEl) titleEl.textContent = 'Transaction Records';
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

async function loadReviewQueueItems() {
  try {
    const res = await api.getReviewQueue(50, 0, state.accountId);
    const items = res?.items || (Array.isArray(res) ? res : []);
    const total = res?.total ?? items.length;
    const tbody = document.getElementById('transactions-full-body');
    const countLabel = document.getElementById('tx-results-count');
    if (!tbody) return;

    countLabel.textContent = `${total} transactions needing categorization review`;

    if (!items || items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 40px;">
            <div style="font-size: 15px; margin-bottom: 6px; color: var(--color-positive);">🎉 Review Queue is clear!</div>
            <div style="font-size: 12px;">All transactions have confirmed categories.</div>
          </td>
        </tr>
      `;
      return;
    }

    renderTableRows(items, true);
  } catch (err) {
    console.error('Failed to load review queue:', err);
    showToast('Failed to load review queue', 'error');
  }
}

let currentTxRequestSeq = 0;
let currentTxAbortController = null;

async function loadTransactions() {
  const reqSeq = ++currentTxRequestSeq;
  if (currentTxAbortController) {
    try { currentTxAbortController.abort(); } catch (e) {}
  }
  currentTxAbortController = new AbortController();

  const tbody = document.getElementById('transactions-full-body');
  if (tbody && currentOffset === 0) {
    tbody.innerHTML = `
      <tr><td colspan="7" style="padding: 16px 14px;"><div class="skeleton skeleton-line" style="width: 88%;"></div></td></tr>
      <tr><td colspan="7" style="padding: 16px 14px;"><div class="skeleton skeleton-line" style="width: 74%;"></div></td></tr>
      <tr><td colspan="7" style="padding: 16px 14px;"><div class="skeleton skeleton-line" style="width: 82%;"></div></td></tr>
    `;
  }

  try {
    let effAccId = null;
    if (activeFilters.account_id === 'ALL') {
      effAccId = null;
    } else if (activeFilters.account_id) {
      effAccId = activeFilters.account_id;
    } else if (state.accountId) {
      effAccId = state.accountId;
    }

    const params = {
      month: state.month,
      category_id: activeFilters.category_id,
      transaction_type: activeFilters.transaction_type,
      essentiality: activeFilters.essentiality,
      search: activeFilters.search,
      limit: PAGE_SIZE,
      offset: currentOffset
    };
    if (effAccId) params.account_id = effAccId;

    const res = await api.getTransactions(params, { signal: currentTxAbortController.signal });
    if (reqSeq !== currentTxRequestSeq) return;
    renderTable(res.items, res.total);
  } catch (err) {
    if (err.name === 'AbortError') return;
    if (reqSeq !== currentTxRequestSeq) return;
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

  renderTableRows(items, false);
}

function renderTableRows(items, isReviewQueueView = false) {
  const tbody = document.getElementById('transactions-full-body');
  if (!tbody) return;

  tbody.innerHTML = items.map(tx => {
    const isIncome = tx.transaction_type === 'income';
    const isRefund = tx.transaction_type === 'refund';
    const isTransfer = tx.transaction_type === 'transfer';
    const isDestTransfer = isTransfer && tx.transfer_role === 'destination';
    const isPositive = isIncome || isRefund || isDestTransfer;
    const sign = isPositive ? '+' : '-';
    const amtClass = isPositive ? 'income' : 'expense';
    const catColor = tx.category_color || '#5B8CFF';
    const needsReview = Boolean(tx.needs_review);
    const merchantName = tx.merchant_name || tx.description || 'Transaction';
    const initials = getMerchantInitials(merchantName);

    let categoryCell = '';
    if (isReviewQueueView) {
      const filteredCats = (state.categories || []).filter(c => c.name !== 'Uncategorized' && (!tx.transaction_type || c.type === tx.transaction_type || !c.type));
      categoryCell = `
        <div class="inline-review-wrap" style="display: flex; align-items: center; gap: 6px;">
          <select class="form-select form-select-sm inline-category-select" data-id="${tx.id}" style="font-size: 12px; padding: 4px 8px; min-width: 140px; background: var(--bg-surface);">
            <option value="">Choose category...</option>
            ${filteredCats.map(c => `<option value="${c.id}" ${c.id === tx.category_id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('')}
          </select>
          <button class="btn btn-primary btn-sm action-inline-resolve" data-id="${tx.id}" style="padding: 4px 10px; font-size: 11.5px; font-weight: 600;" title="Confirm category and update merchant memory">
            Accept
          </button>
        </div>
        ${tx.review_reason ? `<div style="font-size: 10.5px; color: var(--text-muted); margin-top: 3px;">Flagged: ${escapeHtml(tx.review_reason)}</div>` : ''}
      `;
    } else if (needsReview) {
      categoryCell = `
        <span class="review-needed-tag action-quick-resolve" data-id="${tx.id}" title="Click to assign confirmed category">
          <i data-lucide="alert-circle" style="width: 12px; height: 12px;"></i>
          Needs Review
        </span>
        ${tx.review_reason ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(tx.review_reason)}</div>` : ''}
      `;
    } else {
      categoryCell = `
        <span class="tag-pill" style="background: ${catColor}20; color: ${catColor}; border: 1px solid ${catColor}40;">
          ${escapeHtml(tx.category_name || (isTransfer ? 'Transfer' : 'Uncategorized'))}
        </span>
      `;
    }

    const isExpense = tx.transaction_type === 'expense';
    const isLinkedRefund = Boolean(tx.refund_of_transaction_id);
    const isFullyRefunded = tx.remaining_refundable_minor !== undefined && tx.remaining_refundable_minor <= 0;
    const canRefund = isExpense && !isLinkedRefund && !isFullyRefunded;
    const canDuplicate = tx.transaction_type !== 'transfer' && tx.transaction_type !== 'refund';

    return `
      <tr data-id="${tx.id}">
        <td>
          <div style="font-weight: 500;">${escapeHtml(tx.transaction_date)}</div>
          <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(tx.transaction_time || '')}</div>
        </td>
        <td>
          <div class="entity-cell">
            <div class="avatar-chip" style="background: ${catColor}22; color: ${catColor}; border: 1px solid ${catColor}44;" title="${escapeHtml(merchantName)}">
              ${escapeHtml(initials)}
            </div>
            <div>
              <div style="font-weight: 600; color: var(--text-primary);">
                ${escapeHtml(merchantName)}
                ${tx.refund_of_transaction_id ? `<span style="font-size: 10.5px; color: var(--color-positive); margin-left: 6px;">(Refund for #${tx.refund_of_transaction_id})</span>` : ''}
              </div>
              ${tx.note ? `<div style="font-size: 11.5px; color: var(--text-secondary);">${escapeHtml(tx.note)}</div>` : ''}
            </div>
          </div>
        </td>
        <td>
          ${categoryCell}
        </td>
        <td>
          <span style="font-size: 12.5px; color: var(--text-secondary);">${escapeHtml(tx.account_name || 'Everyday')}</span>
          ${tx.transfer_role ? `<span style="font-size: 10px; color: var(--accent-blue); text-transform: uppercase; margin-left: 4px;">(${escapeHtml(tx.transfer_role)})</span>` : ''}
        </td>
        <td>
          <span class="tag-pill" style="background: rgba(255,255,255,0.06); color: var(--text-secondary); text-transform: capitalize;">
            ${escapeHtml(tx.essentiality || 'discretionary')}
          </span>
        </td>
        <td style="text-align: right;">
          <span class="amount-display ${amtClass} num-tabular" style="font-size: 14px;">
            ${sign}${state.formatCurrency(tx.amount, tx.currency)}
          </span>
          ${tx.original_currency && tx.original_currency !== (tx.currency || state.currency) ? `
            <div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">
              ${escapeHtml(tx.original_currency)} ${Number(tx.original_amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          ` : ''}
        </td>
        <td style="text-align: right;">
          <div style="display: inline-flex; align-items: center; gap: 4px;">
            ${canRefund ? `
              <button class="btn btn-secondary btn-icon btn-sm action-refund" data-id="${tx.id}" title="Record Refund for this purchase">
                <i data-lucide="corner-down-left" style="width: 14px; height: 14px;"></i>
              </button>
            ` : (isExpense && !isLinkedRefund ? `
              <button class="btn btn-secondary btn-icon btn-sm" disabled style="opacity: 0.35; cursor: not-allowed;" title="Fully refunded">
                <i data-lucide="corner-down-left" style="width: 14px; height: 14px;"></i>
              </button>
            ` : '')}
            <button class="btn btn-secondary btn-icon btn-sm action-edit" data-id="${tx.id}" title="Edit">
              <i data-lucide="edit-2" style="width: 14px; height: 14px;"></i>
            </button>
            ${canDuplicate ? `
              <button class="btn btn-secondary btn-icon btn-sm action-duplicate" data-id="${tx.id}" title="Duplicate">
                <i data-lucide="copy" style="width: 14px; height: 14px;"></i>
              </button>
            ` : ''}
            <button class="btn btn-danger btn-icon btn-sm action-delete" data-id="${tx.id}" title="Delete (5s Undo Window)">
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
    btn.addEventListener('click', () => {
      const tx = items.find(t => t.id === parseInt(btn.dataset.id));
      if (tx) modals.openTransactionModal(tx);
    });
  });

  tbody.querySelectorAll('.action-quick-resolve').forEach(el => {
    el.addEventListener('click', () => {
      const tx = items.find(t => t.id === parseInt(el.dataset.id));
      if (tx) modals.openTransactionModal(tx);
    });
  });

  tbody.querySelectorAll('.action-inline-resolve').forEach(btn => {
    btn.addEventListener('click', async () => {
      const txId = parseInt(btn.dataset.id, 10);
      const row = btn.closest('tr');
      const select = row?.querySelector('.inline-category-select');
      const catId = select ? parseInt(select.value, 10) : null;
      if (!catId) {
        showToast('Please select a category first', 'warning');
        return;
      }
      const tx = items.find(t => t.id === txId);
      try {
        btn.disabled = true;
        btn.textContent = '...';
        await api.resolveReview(txId, catId, tx?.merchant_name);
        showToast('Category confirmed & learned!', 'success');
        state.notify({ type: 'data_changed' });
        await updateReviewQueueBadge();
        if (isReviewQueueActive) {
          loadReviewQueueItems();
        } else {
          loadTransactions();
        }
      } catch (err) {
        showToast(err.message || 'Failed to resolve review', 'error');
        btn.disabled = false;
        btn.textContent = 'Accept';
      }
    });
  });

  tbody.querySelectorAll('.action-refund').forEach(btn => {
    btn.addEventListener('click', () => {
      const tx = items.find(t => t.id === parseInt(btn.dataset.id));
      if (tx) modals.openRefundModal(tx);
    });
  });

  tbody.querySelectorAll('.action-duplicate').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api.duplicateTransaction(parseInt(btn.dataset.id));
        showToast('Transaction duplicated', 'success');
        state.notify({ type: 'data_changed' });
        if (isReviewQueueActive) {
          loadReviewQueueItems();
        } else {
          loadTransactions();
        }
      } catch (err) {
        showToast(`Duplicate failed: ${err.message}`, 'error');
      }
    });
  });

  // Non-blocking 5-Second Undo Delete Window
  tbody.querySelectorAll('.action-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      const txId = parseInt(btn.dataset.id);
      try {
        await api.deleteTransaction(txId);
        // Refresh display immediately
        if (isReviewQueueActive) {
          loadReviewQueueItems();
        } else {
          loadTransactions();
        }
        await updateReviewQueueBadge();

        // 5-second non-blocking undo window toast
        showToast('Transaction deleted', 'info', 5000, {
          label: 'Undo',
          onClick: async () => {
            try {
              await api.undoDeleteTransaction(txId);
              showToast('Transaction restored', 'success');
              state.notify({ type: 'data_changed' });
              if (isReviewQueueActive) {
                loadReviewQueueItems();
              } else {
                loadTransactions();
              }
              await updateReviewQueueBadge();
            } catch (uErr) {
              showToast(`Undo failed: ${uErr.message}`, 'error');
            }
          }
        });
      } catch (err) {
        showToast(`Delete failed: ${err.message}`, 'error');
      }
    });
  });
}
