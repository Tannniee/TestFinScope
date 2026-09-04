/**
 * FinScope Modals Controller
 * Add/Edit Transaction, Double-Entry Transfer, Budget Editor, and Confirm Dialog
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from './toast.js';

export const modals = {
  activeTxId: null,

  init() {
    this.setupTransactionModal();
    this.setupBudgetModal();
  },

  setupTransactionModal() {
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const closeBtn = document.getElementById('tx-modal-close');
    const cancelBtn = document.getElementById('tx-modal-cancel');
    const form = document.getElementById('tx-form');

    if (!modalOverlay || !form) return;

    const closeModal = () => {
      modalOverlay.classList.remove('open');
      this.activeTxId = null;
      form.reset();
    };

    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) closeModal();
    });

    // Transaction Type segmented button switcher
    const typeButtons = modalOverlay.querySelectorAll('.segmented-btn');
    typeButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        typeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const selectedType = btn.dataset.type;
        document.getElementById('tx-type').value = selectedType;
        this.updateFormFieldsForType(selectedType);
      });
    });

    // Form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const type = document.getElementById('tx-type').value;
      const amount = parseFloat(document.getElementById('tx-amount').value);
      const accountId = parseInt(document.getElementById('tx-account').value);
      const date = document.getElementById('tx-date').value;
      const time = document.getElementById('tx-time').value || '12:00';
      const description = document.getElementById('tx-description').value.trim();
      const note = document.getElementById('tx-note').value.trim();

      if (!amount || isNaN(amount) || amount <= 0) {
        showToast('Please enter a valid amount', 'error');
        return;
      }
      if (!accountId) {
        showToast('Please select an account', 'error');
        return;
      }
      if (!date) {
        showToast('Please select a date', 'error');
        return;
      }

      try {
        if (type === 'transfer') {
          const toAccountId = parseInt(document.getElementById('tx-to-account').value);
          if (!toAccountId) {
            showToast('Please select the destination account', 'error');
            return;
          }
          if (accountId === toAccountId) {
            showToast('Source and destination accounts must be different', 'error');
            return;
          }

          await api.createTransfer({
            from_account_id: accountId,
            to_account_id: toAccountId,
            amount: amount,
            transaction_date: date,
            transaction_time: time,
            description: description || 'Account Transfer',
            note: note
          });
          showToast('Transfer completed successfully', 'success');
        } else {
          // Expense, Income, or Refund
          const categoryId = document.getElementById('tx-category').value ? parseInt(document.getElementById('tx-category').value) : null;
          const merchant = document.getElementById('tx-merchant').value.trim();
          const essentiality = document.getElementById('tx-essentiality').value;
          const isRecurring = document.getElementById('tx-recurring').checked;

          const payload = {
            account_id: accountId,
            category_id: categoryId,
            merchant_name: merchant,
            transaction_type: type,
            amount: amount,
            transaction_date: date,
            transaction_time: time,
            description: description || merchant,
            note: note,
            essentiality: essentiality,
            is_recurring: isRecurring
          };

          if (this.activeTxId) {
            await api.updateTransaction(this.activeTxId, payload);
            showToast('Transaction updated successfully', 'success');
          } else {
            await api.createTransaction(payload);
            const msg = type === 'refund' ? 'Refund recorded successfully' : 'Transaction recorded successfully';
            showToast(msg, 'success');
          }
        }

        closeModal();
        state.notify({ type: 'data_changed' });
      } catch (err) {
        showToast(`Failed to save: ${err.message}`, 'error');
      }
    });
  },

  updateFormFieldsForType(type) {
    const toAccGroup = document.getElementById('group-to-account');
    const catGroup = document.getElementById('group-category');
    const merchantGroup = document.getElementById('group-merchant');
    const essGroup = document.getElementById('group-essentiality');

    if (type === 'transfer') {
      if (toAccGroup) toAccGroup.style.display = 'flex';
      if (catGroup) catGroup.style.display = 'none';
      if (merchantGroup) merchantGroup.style.display = 'none';
      if (essGroup) essGroup.style.display = 'none';
    } else {
      if (toAccGroup) toAccGroup.style.display = 'none';
      if (catGroup) catGroup.style.display = 'flex';
      if (merchantGroup) merchantGroup.style.display = 'block';
      if (essGroup) essGroup.style.display = 'flex';
      this.filterCategoryDropdown(type === 'refund' ? 'expense' : type);
    }
  },

  populateSelectOptions() {
    const accSelect = document.getElementById('tx-account');
    const toAccSelect = document.getElementById('tx-to-account');

    const accOptions = '<option value="">Select Account...</option>' +
      state.accounts.map(a => `<option value="${a.id}">${a.name} (${a.account_type})</option>`).join('');

    if (accSelect) accSelect.innerHTML = accOptions;
    if (toAccSelect) toAccSelect.innerHTML = '<option value="">Select Destination...</option>' +
      state.accounts.map(a => `<option value="${a.id}">${a.name} (${a.account_type})</option>`).join('');

    this.filterCategoryDropdown(document.getElementById('tx-type')?.value || 'expense');
  },

  filterCategoryDropdown(type) {
    const catSelect = document.getElementById('tx-category');
    if (!catSelect) return;
    const currentVal = catSelect.value;
    const catType = type === 'refund' ? 'expense' : type;
    const filtered = state.categories.filter(c => c.type === catType);
    catSelect.innerHTML = '<option value="">Select Category...</option>' +
      filtered.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    if (currentVal) catSelect.value = currentVal;
  },

  openTransactionModal(txData = null, defaultDate = null) {
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const title = document.getElementById('tx-modal-title');
    const form = document.getElementById('tx-form');
    if (!modalOverlay || !form) return;

    this.populateSelectOptions();

    if (txData) {
      this.activeTxId = txData.id;
      title.textContent = 'Edit Transaction';
      document.getElementById('tx-amount').value = txData.amount;
      document.getElementById('tx-account').value = txData.account_id || '';
      document.getElementById('tx-merchant').value = txData.merchant_name || '';
      document.getElementById('tx-date').value = txData.transaction_date || '';
      document.getElementById('tx-time').value = txData.transaction_time || '12:00';
      document.getElementById('tx-description').value = txData.description || '';
      document.getElementById('tx-essentiality').value = txData.essentiality || 'discretionary';
      document.getElementById('tx-recurring').checked = Boolean(txData.is_recurring);
      document.getElementById('tx-note').value = txData.note || '';

      const type = txData.transaction_type || 'expense';
      document.getElementById('tx-type').value = type;
      modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === type);
      });
      this.updateFormFieldsForType(type);
      document.getElementById('tx-category').value = txData.category_id || '';
    } else {
      this.activeTxId = null;
      title.textContent = 'Record Transaction';
      form.reset();
      const todayStr = new Date().toISOString().split('T')[0];
      document.getElementById('tx-date').value = defaultDate || todayStr;
      document.getElementById('tx-time').value = new Date().toTimeString().slice(0, 5);
      document.getElementById('tx-type').value = 'expense';
      modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === 'expense');
      });
      if (state.accounts.length > 0) {
        document.getElementById('tx-account').value = state.accounts[0].id;
      }
      this.updateFormFieldsForType('expense');
    }

    modalOverlay.classList.add('open');
    if (window.lucide) window.lucide.createIcons();
  },

  setupBudgetModal() {
    const modal = document.getElementById('budget-modal-overlay');
    const closeBtn = document.getElementById('budget-modal-close');
    const cancelBtn = document.getElementById('budget-modal-cancel');
    const form = document.getElementById('budget-form');
    if (!modal || !form) return;

    const closeModal = () => modal.classList.remove('open');
    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const catId = parseInt(document.getElementById('budget-category-id').value);
      const amount = parseFloat(document.getElementById('budget-amount').value);
      const month = state.month;

      if (!catId || isNaN(amount) || amount < 0) {
        showToast('Invalid budget values', 'error');
        return;
      }

      try {
        await api.setCategoryBudget(catId, month, amount);
        showToast('Budget saved successfully', 'success');
        closeModal();
        state.notify({ type: 'data_changed' });
      } catch (err) {
        showToast(`Failed to save budget: ${err.message}`, 'error');
      }
    });
  },

  openBudgetModal(categoryId, categoryName, currentAmount = 0) {
    const modal = document.getElementById('budget-modal-overlay');
    if (!modal) return;
    document.getElementById('budget-category-id').value = categoryId;
    document.getElementById('budget-category-name').textContent = categoryName;
    document.getElementById('budget-month-label').textContent = state.formatMonthLabel(state.month);
    document.getElementById('budget-amount').value = currentAmount || '';
    modal.classList.add('open');
  }
};
