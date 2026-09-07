/**
 * Quick Capture Command Bar Component (WP-01).
 * Natural-language transaction entry with Ctrl+K shortcut,
 * live debounced preview, confidence indicators, and keyboard shortcuts.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from './toast.js';
import { modals } from './modals.js';

export const quickCapture = {
  overlay: null,
  input: null,
  previewCard: null,
  loadingSpinner: null,
  validationBox: null,
  currentPreview: null,
  debounceTimer: null,

  init() {
    this.overlay = document.getElementById('quick-capture-overlay');
    this.input = document.getElementById('qc-input');
    this.previewCard = document.getElementById('qc-preview-card');
    this.loadingSpinner = document.getElementById('qc-loading');
    this.validationBox = document.getElementById('qc-validation-box');

    if (!this.overlay || !this.input) return;

    // 1. Global Keyboard Shortcut: Ctrl+K / Cmd+K
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        this.open();
      }
    });

    // 2. Button Triggers
    document.getElementById('btn-quick-capture')?.addEventListener('click', () => {
      this.open();
    });
    document.getElementById('sidebar-quick-capture')?.addEventListener('click', () => {
      this.open();
    });
    document.getElementById('qc-close-btn')?.addEventListener('click', () => {
      this.close();
    });

    // 3. Overlay backdrop click
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) {
        this.close();
      }
    });

    // 4. Input events: debounced preview
    this.input.addEventListener('input', () => {
      clearTimeout(this.debounceTimer);
      const text = this.input.value.trim();
      if (!text) {
        this.clearPreview();
        return;
      }
      if (this.loadingSpinner) this.loadingSpinner.style.display = 'inline-block';
      this.debounceTimer = setTimeout(() => {
        this.fetchPreview(text);
      }, 200);
    });

    // 5. Input keydown: Enter to save, Shift+Enter for modal handoff, Esc to close
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        this.close();
        return;
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) {
          // Shift+Enter handoff to full transaction modal
          this.handoffToModal();
        } else {
          // Enter: Commit immediately
          this.commit();
        }
      }
    });

    // 6. Example chips click
    document.querySelectorAll('.qc-example-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const sample = btn.getAttribute('data-sample');
        if (sample) {
          this.input.value = sample;
          this.input.focus();
          this.fetchPreview(sample);
        }
      });
    });
  },

  open() {
    if (!this.overlay || !this.input) return;
    this.overlay.style.display = 'flex';
    this.input.value = '';
    this.clearPreview();
    setTimeout(() => this.input.focus(), 50);
  },

  close() {
    if (!this.overlay) return;
    this.overlay.style.display = 'none';
    this.clearPreview();
  },

  clearPreview() {
    this.currentPreview = null;
    if (this.previewCard) this.previewCard.style.display = 'none';
    if (this.loadingSpinner) this.loadingSpinner.style.display = 'none';
    if (this.validationBox) {
      this.validationBox.style.display = 'none';
      this.validationBox.textContent = '';
    }
  },

  async fetchPreview(text) {
    try {
      const activeAcctId = state.accountId ? parseInt(state.accountId, 10) : null;
      const resp = await api.previewQuickCapture(text, activeAcctId);
      this.currentPreview = resp;
      this.renderPreview(resp);
    } catch (err) {
      console.warn('Quick capture preview error:', err);
    } finally {
      if (this.loadingSpinner) this.loadingSpinner.style.display = 'none';
    }
  },

  renderPreview(data) {
    if (!this.previewCard || !data) return;

    const parse = data.parse;
    const enrich = data.enrichment;

    // Type badge
    const typeBadge = document.getElementById('qc-chip-type');
    if (typeBadge) {
      typeBadge.textContent = parse.transaction_type === 'income' ? 'Income' : 'Expense';
      typeBadge.className = `qc-badge ${parse.transaction_type === 'income' ? 'qc-badge-income' : 'qc-badge-expense'}`;
    }

    // Amount & Currency
    const amtEl = document.getElementById('qc-preview-amount');
    if (amtEl) {
      if (parse.amount !== null && parse.amount !== undefined) {
        const curr = parse.currency || enrich.account_currency || 'USD';
        amtEl.textContent = state.formatCurrency(parse.amount, curr);
      } else {
        amtEl.textContent = '—';
      }
    }

    // Merchant
    const merchEl = document.getElementById('qc-preview-merchant');
    if (merchEl) {
      merchEl.textContent = enrich.canonical_merchant || parse.merchant_raw || 'Quick Expense';
    }

    // Category & Confidence Pill
    const catEl = document.getElementById('qc-chip-category');
    const confEl = document.getElementById('qc-chip-confidence');
    if (catEl) {
      catEl.textContent = enrich.category_name || 'Uncategorized';
    }
    if (confEl) {
      const pct = Math.round(enrich.category_confidence * 100);
      const src = enrich.category_source;
      confEl.textContent = `${src === 'rule' ? 'Rule' : src === 'merchant_history' ? 'Memory' : src === 'explicit' ? 'Exact' : 'Fallback'} ${pct}%`;
      confEl.className = `qc-confidence-pill ${pct >= 80 ? 'high' : pct >= 50 ? 'medium' : 'low'}`;
    }

    // Account
    const acctEl = document.getElementById('qc-chip-account');
    if (acctEl) {
      acctEl.textContent = enrich.account_name || 'No account';
    }

    // Date
    const dateEl = document.getElementById('qc-chip-date');
    if (dateEl) {
      dateEl.textContent = parse.date_str || 'Today';
    }

    // Validation or errors
    if (this.validationBox) {
      if (data.validation_messages && data.validation_messages.length > 0) {
        this.validationBox.textContent = data.validation_messages.join(' · ');
        this.validationBox.style.display = 'block';
      } else {
        this.validationBox.style.display = 'none';
      }
    }

    this.previewCard.style.display = 'block';
  },

  async commit() {
    if (!this.currentPreview) {
      const text = this.input.value.trim();
      if (!text) return;
      await this.fetchPreview(text);
    }

    if (!this.currentPreview || !this.currentPreview.can_commit) {
      const msg = (this.currentPreview && this.currentPreview.validation_messages && this.currentPreview.validation_messages[0]) || 'Cannot record: check amount or account.';
      showToast(msg, 'error');
      return;
    }

    try {
      const payload = {
        raw_text: this.input.value.trim(),
        account_id: this.currentPreview.enrichment.account_id,
        category_id: this.currentPreview.enrichment.category_id,
        amount: this.currentPreview.parse.amount,
        merchant_name: this.currentPreview.enrichment.canonical_merchant,
        transaction_type: this.currentPreview.parse.transaction_type,
        transaction_date: this.currentPreview.parse.date_str,
        preview_hash: this.currentPreview.enrichment.preview_hash
      };

      const res = await api.commitQuickCapture(payload);
      if (res && res.success) {
        const tx = res.transaction || {};
        const displayAmt = state.formatCurrency(tx.amount || payload.amount, tx.currency || 'USD');
        showToast(`Recorded ${tx.merchant_name || 'Expense'}: ${displayAmt}`, 'success');

        this.close();

        // Refresh global data
        state.notify({ type: 'data_changed' });
        state.loadInitialData();
      }
    } catch (err) {
      showToast(err.message || 'Failed to record transaction', 'error');
    }
  },

  handoffToModal() {
    const preview = this.currentPreview;
    const text = this.input.value.trim();
    this.close();

    const initialData = {};
    if (preview) {
      if (preview.parse.amount) initialData.amount = preview.parse.amount;
      if (preview.parse.transaction_type) initialData.transaction_type = preview.parse.transaction_type;
      if (preview.enrichment.canonical_merchant) initialData.merchant_name = preview.enrichment.canonical_merchant;
      if (preview.enrichment.account_id) initialData.account_id = preview.enrichment.account_id;
      if (preview.enrichment.category_id) initialData.category_id = preview.enrichment.category_id;
      if (preview.parse.date_str) initialData.transaction_date = preview.parse.date_str;
      if (preview.enrichment.essentiality) initialData.essentiality = preview.enrichment.essentiality;
    } else if (text) {
      initialData.description = text;
    }

    modals.openTransactionModal(initialData);
  }
};
