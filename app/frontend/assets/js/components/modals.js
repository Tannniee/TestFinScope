/**
 * FinScope Modals Controller
 * Smart Transaction Capture, Double-Entry Transfer, Refund Workflow, Budget Editor
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from './toast.js';
import { escapeHtml, toLocalDateString, localYesterdayString } from '../utils.js';

export const modals = {
  activeTxId: null,
  isSubmitting: false,
  autocompleteSelectedIndex: -1,
  currentSuggestions: [],

  init() {
    this.setupTransactionModal();
    this.setupBudgetModal();
    this.setupGlobalShortcuts();
  },

  setupGlobalShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Ctrl+N / Cmd+N -> Open Quick Transaction Capture
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n' && !e.shiftKey) {
        e.preventDefault();
        this.openTransactionModal();
        return;
      }

      // Escape -> Close active modal
      if (e.key === 'Escape') {
        const txOverlay = document.getElementById('tx-modal-overlay');
        const budgetOverlay = document.getElementById('budget-modal-overlay');
        if (txOverlay?.classList.contains('open')) {
          this.closeTransactionModal();
        } else if (budgetOverlay?.classList.contains('open')) {
          budgetOverlay.classList.remove('open');
        }
      }
    });
  },

  formSnapshot: null,
  touched: {
    account: false,
    category: false,
    essentiality: false,
    date: false,
    type: false
  },

  resetTouchedState() {
    this.touched = {
      account: false,
      category: false,
      essentiality: false,
      date: false,
      type: false
    };
  },

  _getFormValues() {
    return {
      amount: document.getElementById('tx-amount')?.value || '',
      account: document.getElementById('tx-account')?.value || '',
      merchant: document.getElementById('tx-merchant')?.value || '',
      type: document.getElementById('tx-type')?.value || '',
      date: document.getElementById('tx-date')?.value || '',
      time: document.getElementById('tx-time')?.value || '',
      description: document.getElementById('tx-description')?.value || '',
      note: document.getElementById('tx-note')?.value || '',
      category: document.getElementById('tx-category')?.value || '',
      essentiality: document.getElementById('tx-essentiality')?.value || '',
      recurring: Boolean(document.getElementById('tx-recurring')?.checked),
      toAccount: document.getElementById('tx-to-account')?.value || '',
      toAmount: document.getElementById('tx-to-amount')?.value || '',
      origCurrency: document.getElementById('tx-orig-currency')?.value || '',
      origAmount: document.getElementById('tx-orig-amount')?.value || '',
      refundId: document.getElementById('tx-refund-id')?.value || ''
    };
  },

  captureFormSnapshot() {
    this.formSnapshot = JSON.stringify(this._getFormValues());
  },

  isFormDirty() {
    if (!this.formSnapshot) return false;
    return JSON.stringify(this._getFormValues()) !== this.formSnapshot;
  },

  closeTransactionModal(force = false) {
    if (!force && this.isFormDirty()) {
      if (!confirm('You have unsaved changes. Are you sure you want to discard them?')) {
        return;
      }
    }
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const form = document.getElementById('tx-form');
    if (!modalOverlay) return;
    modalOverlay.classList.remove('open');
    this.activeTxId = null;
    this.formSnapshot = null;
    this.hideAutocomplete();
    if (form) form.reset();
  },

  setupTransactionModal() {
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const closeBtn = document.getElementById('tx-modal-close');
    const cancelBtn = document.getElementById('tx-modal-cancel');
    const form = document.getElementById('tx-form');
    const saveAddBtn = document.getElementById('tx-modal-save-add');
    const moreDetailsToggle = document.getElementById('more-details-toggle');
    const moreDetailsBody = document.getElementById('more-details-body');
    const payeeInput = document.getElementById('tx-merchant');

    if (!modalOverlay || !form) return;

    closeBtn?.addEventListener('click', () => this.closeTransactionModal());
    cancelBtn?.addEventListener('click', () => this.closeTransactionModal());
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) this.closeTransactionModal();
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

    // Progressive Disclosure Toggle
    moreDetailsToggle?.addEventListener('click', () => {
      const isOpen = moreDetailsBody?.classList.toggle('open');
      const span = moreDetailsToggle.querySelector('span');
      const icon = moreDetailsToggle.querySelector('i');
      if (span) span.textContent = isOpen ? 'Fewer Details' : 'More Details';
      if (icon) icon.style.transform = isOpen ? 'rotate(180deg)' : 'rotate(0deg)';
    });

    // Quick Date Pills
    this.setupDatePills();

    // Payee Autocomplete & Merchant Memory
    this.setupPayeeAutocomplete(payeeInput);

    // Account & field touched tracking (P0-03)
    document.getElementById('tx-account')?.addEventListener('change', () => {
      this.touched.account = true;
      this.updateCurrencySymbol();
    });
    document.getElementById('tx-to-account')?.addEventListener('change', () => {
      this.updateCurrencySymbol();
    });
    document.getElementById('tx-category')?.addEventListener('change', () => {
      this.touched.category = true;
    });
    document.getElementById('tx-essentiality')?.addEventListener('change', () => {
      this.touched.essentiality = true;
    });
    document.getElementById('tx-date')?.addEventListener('change', () => {
      this.touched.date = true;
    });

    // Save & Add Another handler
    saveAddBtn?.addEventListener('click', async (e) => {
      e.preventDefault();
      await this.handleTransactionSubmit(true);
    });

    // Form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleTransactionSubmit(false);
    });

    // Modal keyboard shortcuts (Ctrl+Enter, Ctrl+Shift+Enter)
    form.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) {
          this.handleTransactionSubmit(true);
        } else {
          this.handleTransactionSubmit(false);
        }
      }
    });
  },

  setupDatePills() {
    const pills = document.querySelectorAll('.quick-date-btn');
    const dateInput = document.getElementById('tx-date');
    if (!dateInput) return;

    pills.forEach(pill => {
      pill.addEventListener('click', () => {
        pills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        const dateType = pill.dataset.date;

        if (dateType === 'today') {
          dateInput.value = toLocalDateString();
          dateInput.style.display = 'none';
        } else if (dateType === 'yesterday') {
          dateInput.value = localYesterdayString();
          dateInput.style.display = 'none';
        } else if (dateType === 'pick') {
          dateInput.style.display = 'inline-block';
          dateInput.focus();
        }
      });
    });

    dateInput.addEventListener('change', () => {
      const selected = dateInput.value;
      const todayStr = toLocalDateString();
      const yesterdayStr = localYesterdayString();

      pills.forEach(p => p.classList.remove('active'));
      if (selected === todayStr) {
        document.querySelector('.quick-date-btn[data-date="today"]')?.classList.add('active');
        dateInput.style.display = 'none';
      } else if (selected === yesterdayStr) {
        document.querySelector('.quick-date-btn[data-date="yesterday"]')?.classList.add('active');
        dateInput.style.display = 'none';
      } else {
        document.querySelector('.quick-date-btn[data-date="pick"]')?.classList.add('active');
        dateInput.style.display = 'inline-block';
      }
    });
  },

  setupPayeeAutocomplete(payeeInput) {
    const box = document.getElementById('payee-autocomplete-box');
    if (!payeeInput || !box) return;

    let debounceTimer = null;

    const fetchSuggestions = async (query) => {
      try {
        if (!query) {
          const recent = await api.getRecentPayees(6);
          this.currentSuggestions = (recent || []).map(p => this.normalizeSuggestion({
            ...p,
            confidence: 'recent',
            tx_count: p.transaction_count
          }));
        } else {
          const res = await api.getMerchantSuggestions(query, 6);
          const raw = res?.suggestions || [];
          this.currentSuggestions = raw.map(s => this.normalizeSuggestion(s));
        }
        this.renderAutocompleteDropdown();
      } catch (err) {
        console.warn('Payee autocomplete fetch error:', err);
      }
    };

    payeeInput.addEventListener('focus', () => {
      if (!payeeInput.value.trim()) {
        fetchSuggestions('');
      }
    });

    payeeInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      const query = e.target.value.trim();
      this.autocompleteSelectedIndex = -1;
      debounceTimer = setTimeout(() => {
        fetchSuggestions(query);
      }, 140);
    });

    payeeInput.addEventListener('keydown', (e) => {
      if (!box.classList.contains('show') || this.currentSuggestions.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.autocompleteSelectedIndex = Math.min(this.autocompleteSelectedIndex + 1, this.currentSuggestions.length - 1);
        this.updateActiveSuggestionItem();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.autocompleteSelectedIndex = Math.max(this.autocompleteSelectedIndex - 1, 0);
        this.updateActiveSuggestionItem();
      } else if (e.key === 'Enter') {
        if (this.autocompleteSelectedIndex >= 0 && this.autocompleteSelectedIndex < this.currentSuggestions.length) {
          e.preventDefault();
          this.applyPayeeSuggestion(this.currentSuggestions[this.autocompleteSelectedIndex]);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.hideAutocomplete();
      }
    });

    document.addEventListener('click', (e) => {
      if (!payeeInput.contains(e.target) && !box.contains(e.target)) {
        this.hideAutocomplete();
      }
    });
  },

  renderAutocompleteDropdown() {
    const box = document.getElementById('payee-autocomplete-box');
    if (!box) return;

    if (!this.currentSuggestions || this.currentSuggestions.length === 0) {
      this.hideAutocomplete();
      return;
    }

    box.innerHTML = this.currentSuggestions.map((s, idx) => {
      const confBadge = s.confidence === 'high' 
        ? `<span class="confidence-tag high">High Match</span>`
        : s.confidence === 'recent'
        ? `<span class="confidence-tag recent">Recent</span>`
        : s.confidence === 'moderate'
        ? `<span class="confidence-tag moderate">Suggested</span>`
        : '';

      const catHint = s.category_name ? `<span class="payee-cat-hint">📁 ${escapeHtml(s.category_name)}</span>` : '';

      return `
        <div class="payee-autocomplete-item" data-idx="${idx}">
          <div class="payee-info">
            <span class="payee-name">${escapeHtml(s.name)}</span>
            ${catHint}
          </div>
          ${confBadge}
        </div>
      `;
    }).join('');

    box.querySelectorAll('.payee-autocomplete-item').forEach(el => {
      el.addEventListener('click', () => {
        const idx = parseInt(el.dataset.idx);
        if (this.currentSuggestions[idx]) {
          this.applyPayeeSuggestion(this.currentSuggestions[idx]);
        }
      });
    });

    box.classList.add('show');
    this.autocompleteSelectedIndex = -1;
  },

  updateActiveSuggestionItem() {
    const box = document.getElementById('payee-autocomplete-box');
    if (!box) return;
    const items = box.querySelectorAll('.payee-autocomplete-item');
    items.forEach((it, i) => {
      if (i === this.autocompleteSelectedIndex) {
        it.classList.add('active');
        it.scrollIntoView({ block: 'nearest' });
      } else {
        it.classList.remove('active');
      }
    });
  },

  normalizeSuggestion(p) {
    if (!p) return null;
    const name = p.name || p.merchant_name || '';
    const categoryId = p.default_category_id != null ? p.default_category_id : p.category_id;
    const accountId = p.preferred_account_id != null ? p.preferred_account_id : p.account_id;
    const essentiality = p.default_essentiality || p.essentiality || 'discretionary';
    return {
      ...p,
      name,
      merchant_name: name,
      default_category_id: categoryId,
      category_id: categoryId,
      preferred_account_id: accountId,
      account_id: accountId,
      default_essentiality: essentiality,
      essentiality
    };
  },

  applyPayeeSuggestion(rawSuggestion) {
    const suggestion = this.normalizeSuggestion(rawSuggestion);
    if (!suggestion) return;

    const payeeInput = document.getElementById('tx-merchant');
    if (payeeInput) payeeInput.value = suggestion.name;

    // Smart autofill Category (respect touched state)
    if (!this.touched.category && suggestion.default_category_id) {
      const catSelect = document.getElementById('tx-category');
      if (catSelect && Array.from(catSelect.options).some(opt => parseInt(opt.value) === suggestion.default_category_id)) {
        catSelect.value = suggestion.default_category_id;
      }
    }

    // Smart autofill Account (respect touched state & refresh currency UI)
    if (!this.touched.account && suggestion.preferred_account_id) {
      const accSelect = document.getElementById('tx-account');
      if (accSelect && Array.from(accSelect.options).some(opt => parseInt(opt.value) === suggestion.preferred_account_id)) {
        accSelect.value = suggestion.preferred_account_id;
        this.updateCurrencySymbol();
      }
    }

    // Smart autofill Essentiality (respect touched state)
    if (!this.touched.essentiality && suggestion.default_essentiality) {
      const essSelect = document.getElementById('tx-essentiality');
      if (essSelect) essSelect.value = suggestion.default_essentiality;
    }

    this.hideAutocomplete();
  },

  resetTransactionFormForNextCapture({ preserveDate = true, preserveAccount = true } = {}) {
    const amtInput = document.getElementById('tx-amount');
    const merchantInput = document.getElementById('tx-merchant');
    const descInput = document.getElementById('tx-description');
    const noteInput = document.getElementById('tx-note');
    const catSelect = document.getElementById('tx-category');
    const essSelect = document.getElementById('tx-essentiality');
    const recurringCheck = document.getElementById('tx-recurring');
    const origCurrInput = document.getElementById('tx-orig-currency');
    const origAmtInput = document.getElementById('tx-orig-amount');
    const toAccSelect = document.getElementById('tx-to-account');
    const toAmtInput = document.getElementById('tx-to-amount');
    const refundIdInput = document.getElementById('tx-refund-id');

    if (amtInput) amtInput.value = '';
    if (merchantInput) merchantInput.value = '';
    if (descInput) descInput.value = '';
    if (noteInput) noteInput.value = '';
    if (catSelect) catSelect.value = '';
    if (essSelect) essSelect.value = 'unknown';
    if (recurringCheck) recurringCheck.checked = false;
    if (origCurrInput) origCurrInput.value = '';
    if (origAmtInput) origAmtInput.value = '';
    if (toAccSelect) toAccSelect.value = '';
    if (toAmtInput) toAmtInput.value = '';
    if (refundIdInput) refundIdInput.value = '';

    if (!preserveAccount) {
      const accSelect = document.getElementById('tx-account');
      if (accSelect && accSelect.options.length > 0) {
        accSelect.selectedIndex = 0;
      }
    }

    if (!preserveDate) {
      const dateInput = document.getElementById('tx-date');
      if (dateInput) dateInput.value = toLocalDateString();
    }

    this.resetTouchedState();
    if (preserveAccount) this.touched.account = true;
    if (preserveDate) this.touched.date = true;

    this.hideAutocomplete();
    this.updateCurrencySymbol();
    this.captureFormSnapshot();
    amtInput?.focus();
  },

  hideAutocomplete() {
    const box = document.getElementById('payee-autocomplete-box');
    if (box) {
      box.classList.remove('show');
      box.innerHTML = '';
    }
    this.autocompleteSelectedIndex = -1;
  },

  async handleTransactionSubmit(isSaveAndAddAnother = false) {
    if (this.isSubmitting) return;

    const type = document.getElementById('tx-type').value;
    const amountVal = document.getElementById('tx-amount').value;
    const amount = parseFloat(amountVal);
    const accountId = parseInt(document.getElementById('tx-account').value);
    const date = document.getElementById('tx-date').value;
    const time = document.getElementById('tx-time').value || '12:00';
    const description = document.getElementById('tx-description').value.trim();
    const note = document.getElementById('tx-note').value.trim();

    if (!amount || isNaN(amount) || amount <= 0) {
      showToast('Please enter a valid amount', 'error');
      document.getElementById('tx-amount')?.focus();
      return;
    }
    if (!accountId) {
      showToast('Please select an account', 'error');
      document.getElementById('tx-account')?.focus();
      return;
    }
    if (!date) {
      showToast('Please select a date', 'error');
      return;
    }

    const submitBtn = document.querySelector('#tx-form button[type="submit"]');
    const saveAddBtn = document.getElementById('tx-modal-save-add');
    const originalSubmitText = submitBtn ? submitBtn.textContent : 'Save';

    this.isSubmitting = true;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving...';
    }
    if (saveAddBtn) saveAddBtn.disabled = true;

    try {
      if (type === 'transfer') {
        const toAccountId = parseInt(document.getElementById('tx-to-account').value);
        if (!toAccountId) {
          showToast('Please select the destination account', 'error');
          document.getElementById('tx-to-account')?.focus();
          return;
        }
        if (accountId === toAccountId) {
          showToast('Source and destination accounts must be different', 'error');
          return;
        }

        const toAmountVal = document.getElementById('tx-to-amount')?.value;
        const toAmount = toAmountVal ? parseFloat(toAmountVal) : null;

        const transferPayload = {
          from_account_id: accountId,
          to_account_id: toAccountId,
          amount: amount,
          transaction_date: date,
          transaction_time: time,
          description: description || 'Account Transfer',
          note: note
        };
        if (toAmount && !isNaN(toAmount) && toAmount > 0) {
          transferPayload.to_amount = toAmount;
        }

        if (this.activeTxId) {
          transferPayload.tx_id = this.activeTxId;
          await api.updateTransfer(transferPayload);
          showToast('Transfer updated successfully', 'success');
        } else {
          await api.createTransfer(transferPayload);
          showToast('Transfer completed successfully', 'success');
        }
      } else if (type === 'refund') {
        const refundTxIdVal = document.getElementById('tx-refund-id').value.trim();
        const refundTxId = refundTxIdVal ? parseInt(refundTxIdVal, 10) : null;

        if (this.activeTxId) {
          await api.updateRefund({
            tx_id: this.activeTxId,
            amount: amount,
            transaction_date: date,
            note: note,
            account_id: accountId
          });
          showToast('Refund updated successfully', 'success');
        } else if (refundTxId && !isNaN(refundTxId) && refundTxId > 0) {
          await api.createRefund({
            original_transaction_id: refundTxId,
            amount: amount,
            account_id: accountId,
            transaction_date: date,
            transaction_time: time,
            description: description || `Refund for #${refundTxId}`,
            note: note
          });
          showToast('Linked refund recorded successfully', 'success');
        } else {
          showToast('Original Transaction ID is required for refunds', 'error');
          document.getElementById('tx-refund-id')?.focus();
          return;
        }
      } else {
        // Expense or Income
        const categoryId = document.getElementById('tx-category').value ? parseInt(document.getElementById('tx-category').value) : null;
        const merchant = document.getElementById('tx-merchant').value.trim();
        const essentiality = document.getElementById('tx-essentiality').value;
        const isRecurring = document.getElementById('tx-recurring').checked;
        const origCurr = document.getElementById('tx-orig-currency')?.value.trim().toUpperCase();
        const origAmtVal = document.getElementById('tx-orig-amount')?.value;
        const origAmount = origAmtVal ? parseFloat(origAmtVal) : null;

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

        if (origCurr) {
          payload.original_currency = origCurr;
          if (origAmount && !isNaN(origAmount) && origAmount > 0) {
            payload.original_amount = origAmount;
          }
        }

        if (this.activeTxId) {
          await api.updateTransaction(this.activeTxId, payload);
          showToast('Transaction updated successfully', 'success');
        } else {
          await api.createTransaction(payload);
          const msg = type === 'income' ? 'Income recorded' : 'Expense recorded';
          showToast(msg, 'success');
        }
      }

      state.notify({ type: 'data_changed' });

      if (isSaveAndAddAnother && !this.activeTxId) {
        this.resetTransactionFormForNextCapture({ preserveDate: true, preserveAccount: true });
        showToast('Ready for next transaction', 'info', 1800);
      } else {
        this.closeTransactionModal(true);
      }
    } catch (err) {
      showToast(`Failed to save: ${err.message}`, 'error');
    } finally {
      this.isSubmitting = false;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalSubmitText;
      }
      if (saveAddBtn) saveAddBtn.disabled = false;
    }
  },

  updateFormFieldsForType(type) {
    const toAccGroup = document.getElementById('group-to-account');
    const toAmtGroup = document.getElementById('group-to-amount');
    const catGroup = document.getElementById('group-category');
    const merchantGroup = document.getElementById('group-merchant');
    const essGroup = document.getElementById('group-essentiality');
    const refundGroup = document.getElementById('group-refund-ref');
    const labelAccount = document.getElementById('label-account');

    if (type === 'transfer') {
      if (toAccGroup) toAccGroup.style.display = 'flex';
      if (toAmtGroup) toAmtGroup.style.display = 'flex';
      if (catGroup) catGroup.style.display = 'none';
      if (merchantGroup) merchantGroup.style.display = 'none';
      if (essGroup) essGroup.style.display = 'none';
      if (refundGroup) refundGroup.style.display = 'none';
      if (labelAccount) labelAccount.textContent = 'Source Account';
    } else if (type === 'refund') {
      if (toAccGroup) toAccGroup.style.display = 'none';
      if (toAmtGroup) toAmtGroup.style.display = 'none';
      if (labelAccount) labelAccount.textContent = 'Account';
      if (catGroup) catGroup.style.display = 'flex';
      if (merchantGroup) merchantGroup.style.display = 'block';
      if (essGroup) essGroup.style.display = 'none';
      if (refundGroup) refundGroup.style.display = 'block';
      this.filterCategoryDropdown('expense');
    } else {
      if (toAccGroup) toAccGroup.style.display = 'none';
      if (toAmtGroup) toAmtGroup.style.display = 'none';
      if (labelAccount) labelAccount.textContent = 'Account';
      if (catGroup) catGroup.style.display = 'flex';
      if (merchantGroup) merchantGroup.style.display = 'block';
      if (essGroup) essGroup.style.display = 'flex';
      if (refundGroup) refundGroup.style.display = 'none';
      this.filterCategoryDropdown(type);
    }
  },

  populateSelectOptions() {
    const accSelect = document.getElementById('tx-account');
    const toAccSelect = document.getElementById('tx-to-account');

    const accOptions = '<option value="">Select Account...</option>' +
      state.accounts.map(a => `<option value="${escapeHtml(a.id)}" data-currency="${escapeHtml(a.currency || 'USD')}">${escapeHtml(a.name)} (${escapeHtml(a.currency || 'USD')} - ${escapeHtml(a.account_type)})</option>`).join('');

    if (accSelect) accSelect.innerHTML = accOptions;
    if (toAccSelect) toAccSelect.innerHTML = '<option value="">Select Destination...</option>' +
      state.accounts.map(a => `<option value="${escapeHtml(a.id)}" data-currency="${escapeHtml(a.currency || 'USD')}">${escapeHtml(a.name)} (${escapeHtml(a.currency || 'USD')} - ${escapeHtml(a.account_type)})</option>`).join('');

    this.filterCategoryDropdown(document.getElementById('tx-type')?.value || 'expense');
    this.updateCurrencySymbol();
  },

  updateCurrencySymbol() {
    const accSelect = document.getElementById('tx-account');
    const symbolEl = document.getElementById('tx-currency-symbol');
    if (!accSelect || !symbolEl) return;
    const selectedOpt = accSelect.options[accSelect.selectedIndex];
    const curr = selectedOpt?.dataset?.currency || state.currency || 'USD';
    const symbol = state.currencyCatalog?.get(curr)?.symbol || { USD: '$', EUR: '€', GBP: '£', JPY: '¥', VND: '₫' }[curr] || curr;
    symbolEl.textContent = symbol;

    const fractionDigits = (typeof state.getMinorUnit === 'function') ? state.getMinorUnit(curr) : ((curr === 'VND' || curr === 'JPY' || curr === 'KRW') ? 0 : (curr === 'KWD' || curr === 'BHD' ? 3 : 2));
    const stepVal = (typeof state.getAmountStep === 'function') ? state.getAmountStep(curr) : (fractionDigits === 0 ? '1' : (fractionDigits === 3 ? '0.001' : '0.01'));
    const placeholderVal = fractionDigits === 0 ? '0' : (fractionDigits === 3 ? '0.000' : '0.00');

    const amtInput = document.getElementById('tx-amount');
    if (amtInput) {
      amtInput.step = stepVal;
      amtInput.placeholder = placeholderVal;
    }

    const toAccSelect = document.getElementById('tx-to-account');
    const toAmtInput = document.getElementById('tx-to-amount');
    if (toAccSelect && toAmtInput) {
      const toOpt = toAccSelect.options[toAccSelect.selectedIndex];
      const toCurr = toOpt?.dataset?.currency || curr;
      const toDigits = (typeof state.getMinorUnit === 'function') ? state.getMinorUnit(toCurr) : ((toCurr === 'VND' || toCurr === 'JPY' || toCurr === 'KRW') ? 0 : (toCurr === 'KWD' || toCurr === 'BHD' ? 3 : 2));
      toAmtInput.step = (typeof state.getAmountStep === 'function') ? state.getAmountStep(toCurr) : (toDigits === 0 ? '1' : (toDigits === 3 ? '0.001' : '0.01'));
      toAmtInput.placeholder = toDigits === 0 ? '0' : (toDigits === 3 ? '0.000' : '0.00');
    }
  },

  filterCategoryDropdown(type) {
    const catSelect = document.getElementById('tx-category');
    if (!catSelect) return;
    const currentVal = catSelect.value;
    const catType = type === 'refund' ? 'expense' : type;
    const filtered = state.categories.filter(c => c.type === catType);
    catSelect.innerHTML = '<option value="">Select Category...</option>' +
      filtered.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('');
    if (currentVal) catSelect.value = currentVal;
  },

  openTransactionModal(txData = null, defaultDateOrOptions = null) {
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const title = document.getElementById('tx-modal-title');
    const form = document.getElementById('tx-form');
    const saveAddBtn = document.getElementById('tx-modal-save-add');
    const moreDetailsBody = document.getElementById('more-details-body');
    const moreDetailsToggle = document.getElementById('more-details-toggle');
    if (!modalOverlay || !form) return;

    this.populateSelectOptions();

    const options = (typeof defaultDateOrOptions === 'object' && defaultDateOrOptions !== null)
      ? defaultDateOrOptions
      : { defaultDate: defaultDateOrOptions };

    const isEditMode = options.mode === 'edit' || (Boolean(txData) && txData.id != null && options.mode !== 'create');

    // Synchronize date pills with activeDate (UX-H04)
    const activeDate = txData?.transaction_date || options.defaultDate || toLocalDateString();
    const todayStr = toLocalDateString();
    const yesterdayStr = localYesterdayString();

    document.querySelectorAll('.quick-date-btn').forEach(p => p.classList.remove('active'));
    const dateInput = document.getElementById('tx-date');
    if (dateInput) {
      dateInput.value = activeDate;
      if (activeDate === todayStr) {
        document.querySelector('.quick-date-btn[data-date="today"]')?.classList.add('active');
        dateInput.style.display = 'none';
      } else if (activeDate === yesterdayStr) {
        document.querySelector('.quick-date-btn[data-date="yesterday"]')?.classList.add('active');
        dateInput.style.display = 'none';
      } else {
        document.querySelector('.quick-date-btn[data-date="pick"]')?.classList.add('active');
        dateInput.style.display = 'inline-block';
      }
    }

    const origCurrInput = document.getElementById('tx-orig-currency');
    const origAmtInput = document.getElementById('tx-orig-amount');
    const toAmtInput = document.getElementById('tx-to-amount');

    if (isEditMode) {
      this.activeTxId = txData.id;
      title.textContent = 'Edit Transaction';
      this.touched = { account: true, category: true, essentiality: true, date: true, type: true };
      if (saveAddBtn) saveAddBtn.style.display = 'none'; // Editing single transaction

      document.getElementById('tx-amount').value = txData.amount;
      document.getElementById('tx-account').value = txData.account_id || '';
      document.getElementById('tx-merchant').value = txData.merchant_name || '';
      document.getElementById('tx-time').value = txData.transaction_time || '12:00';
      document.getElementById('tx-description').value = txData.description || '';
      document.getElementById('tx-essentiality').value = txData.essentiality || 'unknown';
      document.getElementById('tx-recurring').checked = Boolean(txData.is_recurring);
      document.getElementById('tx-note').value = txData.note || '';
      if (origCurrInput) origCurrInput.value = txData.original_currency || '';
      if (origAmtInput) origAmtInput.value = txData.original_amount || '';
      if (toAmtInput) toAmtInput.value = '';

      const type = txData.transaction_type || 'expense';
      document.getElementById('tx-type').value = type;
      const isSpecial = type === 'transfer' || type === 'refund';
      modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === type);
        btn.disabled = isSpecial;
        btn.style.pointerEvents = isSpecial ? 'none' : 'auto';
        btn.style.opacity = isSpecial ? (btn.dataset.type === type ? '1' : '0.4') : '1';
      });
      this.updateFormFieldsForType(type);
      document.getElementById('tx-category').value = txData.category_id || '';

      // Pre-fill transfer destination account & amount if editing transfer (PR 4 / V121-M03)
      if (type === 'transfer') {
        const destAccId = txData.to_account_id || txData.linked_account_id;
        if (destAccId) {
          const toAccSelect = document.getElementById('tx-to-account');
          if (toAccSelect) toAccSelect.value = destAccId;
        }
        if (txData.destination_amount != null && toAmtInput) {
          toAmtInput.value = txData.destination_amount;
        }
      } else if (type === 'refund') {
        if (txData.refund_of_transaction_id) {
          const refundInput = document.getElementById('tx-refund-id');
          if (refundInput) refundInput.value = txData.refund_of_transaction_id;
        }
      }

      this.updateCurrencySymbol();

      // Auto-open more details if editing an item with memo, non-default essentiality, note, or foreign currency
      if (txData.description || txData.note || txData.is_recurring || txData.original_currency) {
        moreDetailsBody?.classList.add('open');
        const span = moreDetailsToggle?.querySelector('span');
        if (span) span.textContent = 'Fewer Details';
      }
    } else {
      // Creation mode (brand new or prefilled handoff)
      this.activeTxId = null;
      title.textContent = 'Record Transaction';
      this.resetTouchedState();
      if (saveAddBtn) saveAddBtn.style.display = 'inline-block';
      form.reset();
      if (origCurrInput) origCurrInput.value = '';
      if (origAmtInput) origAmtInput.value = '';
      if (toAmtInput) toAmtInput.value = '';
      moreDetailsBody?.classList.remove('open');
      const span = moreDetailsToggle?.querySelector('span');
      if (span) span.textContent = 'More Details';

      const defaultAcc = (state.accountId && state.accounts.some(a => a.id === state.accountId))
        ? state.accountId
        : (state.accounts.length > 0 ? state.accounts[0].id : '');

      if (txData) {
        // Prefilled creation (e.g. from quick-capture Shift+Enter handoff)
        document.getElementById('tx-amount').value = txData.amount != null ? txData.amount : '';
        document.getElementById('tx-account').value = txData.account_id || defaultAcc;
        document.getElementById('tx-merchant').value = txData.merchant_name || '';
        document.getElementById('tx-time').value = txData.transaction_time || new Date().toTimeString().slice(0, 5);
        document.getElementById('tx-description').value = txData.description || '';
        document.getElementById('tx-essentiality').value = txData.essentiality || 'unknown';
        document.getElementById('tx-recurring').checked = Boolean(txData.is_recurring);
        document.getElementById('tx-note').value = txData.note || '';
        if (origCurrInput) origCurrInput.value = txData.original_currency || '';
        if (origAmtInput) origAmtInput.value = txData.original_amount != null ? txData.original_amount : '';

        const type = txData.transaction_type || 'expense';
        document.getElementById('tx-type').value = type;
        modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
          btn.classList.toggle('active', btn.dataset.type === type);
          btn.disabled = false;
          btn.style.pointerEvents = 'auto';
          btn.style.opacity = '1';
        });
        this.updateFormFieldsForType(type);
        if (txData.category_id) {
          document.getElementById('tx-category').value = txData.category_id;
        }

        // Auto-expand details if foreign currency or additional metadata present
        if (txData.original_currency || txData.description || txData.note || txData.is_recurring) {
          moreDetailsBody?.classList.add('open');
          if (span) span.textContent = 'Fewer Details';
        }
      } else {
        // Standard blank creation
        document.getElementById('tx-date').value = activeDate;
        document.getElementById('tx-time').value = new Date().toTimeString().slice(0, 5);
        document.getElementById('tx-type').value = 'expense';
        modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
          btn.classList.toggle('active', btn.dataset.type === 'expense');
          btn.disabled = false;
          btn.style.pointerEvents = 'auto';
          btn.style.opacity = '1';
        });
        document.getElementById('tx-account').value = defaultAcc;
        this.updateFormFieldsForType('expense');
      }
      this.updateCurrencySymbol();
    }

    this.captureFormSnapshot();
    modalOverlay.classList.add('open');
    if (window.lucide) window.lucide.createIcons();

    // Focus hero Amount field immediately for 3-10s quick capture
    setTimeout(() => {
      const amtInput = document.getElementById('tx-amount');
      if (amtInput) {
        amtInput.focus();
        amtInput.select();
      }
    }, 60);
  },

  async openRefundModal(originalTx) {
    let refundable = null;
    try {
      refundable = await api.getRefundableInfo(originalTx.id);
    } catch (e) {
      console.warn('Could not fetch refundable info:', e);
    }

    if (refundable && !refundable.can_refund) {
      showToast('This transaction has already been fully refunded.', 'warning');
      return;
    }

    this.openTransactionModal();
    const modalOverlay = document.getElementById('tx-modal-overlay');
    const title = document.getElementById('tx-modal-title');
    if (title) title.textContent = 'Record Refund';

    // Switch type to refund
    document.getElementById('tx-type').value = 'refund';
    modalOverlay.querySelectorAll('.segmented-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.type === 'refund');
    });
    this.updateFormFieldsForType('refund');

    // Pre-fill remaining refundable amount in purchase currency
    const initialAmount = refundable ? refundable.remaining_refundable : originalTx.amount;
    document.getElementById('tx-amount').value = initialAmount;
    document.getElementById('tx-account').value = originalTx.account_id || '';
    document.getElementById('tx-merchant').value = originalTx.merchant_name || '';
    document.getElementById('tx-category').value = originalTx.category_id || '';
    document.getElementById('tx-refund-id').value = originalTx.id;
    document.getElementById('tx-description').value = `Refund for ${originalTx.merchant_name || originalTx.description || 'purchase'}`;

    this.updateCurrencySymbol();
    this.captureFormSnapshot();

    if (refundable) {
      const origCurr = refundable.original_currency;
      const remFormatted = state.formatCurrency(refundable.remaining_refundable, origCurr);
      showToast(`Remaining refundable balance: ${remFormatted}`, 'info', 3500);
    }
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
