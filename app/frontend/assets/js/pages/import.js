/**
 * FinScope Bank CSV Import Wizard
 * 4-Step Interactive Workflow:
 * 1. Upload/Paste CSV & Account Select
 * 2. Column Mapping
 * 3. Duplicate Detection & Review
 * 4. Batch Commit & Confirmation
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../utils.js';

let importStep = 1;
let rawCsvText = '';
let selectedAccountId = null;
let detectedHeaders = [];
let currentMapping = {};
let previewData = null;

export async function renderImportPage(container) {
  importStep = 1;
  rawCsvText = '';
  selectedAccountId = state.accountId || (state.accounts[0]?.id || null);

  container.innerHTML = `
    <div class="import-view" style="max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px;">
      <!-- Wizard Progress Steps -->
      <div class="fin-card" style="padding: 20px 28px;">
        <div style="display: flex; align-items: center; justify-content: space-between; position: relative;">
          <div class="wizard-step ${importStep === 1 ? 'active' : (importStep > 1 ? 'completed' : '')}" id="step-indicator-1" style="display: flex; align-items: center; gap: 10px;">
            <div class="step-badge" style="width: 30px; height: 30px; border-radius: 50%; background: var(--accent-blue); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">1</div>
            <div>
              <div style="font-weight: 600; font-size: 13px;">Upload CSV</div>
              <div style="font-size: 11px; color: var(--text-muted);">Choose file & account</div>
            </div>
          </div>

          <div style="flex: 1; height: 2px; background: var(--border-subtle); margin: 0 16px;"></div>

          <div class="wizard-step ${importStep === 2 ? 'active' : (importStep > 2 ? 'completed' : '')}" id="step-indicator-2" style="display: flex; align-items: center; gap: 10px; opacity: 0.5;">
            <div class="step-badge" style="width: 30px; height: 30px; border-radius: 50%; background: var(--bg-card-subtle); border: 1px solid var(--border-medium); color: var(--text-muted); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">2</div>
            <div>
              <div style="font-weight: 600; font-size: 13px;">Map Columns</div>
              <div style="font-size: 11px; color: var(--text-muted);">Match fields</div>
            </div>
          </div>

          <div style="flex: 1; height: 2px; background: var(--border-subtle); margin: 0 16px;"></div>

          <div class="wizard-step ${importStep === 3 ? 'active' : (importStep > 3 ? 'completed' : '')}" id="step-indicator-3" style="display: flex; align-items: center; gap: 10px; opacity: 0.5;">
            <div class="step-badge" style="width: 30px; height: 30px; border-radius: 50%; background: var(--bg-card-subtle); border: 1px solid var(--border-medium); color: var(--text-muted); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">3</div>
            <div>
              <div style="font-weight: 600; font-size: 13px;">Preview & Duplicates</div>
              <div style="font-size: 11px; color: var(--text-muted);">Verify records</div>
            </div>
          </div>

          <div style="flex: 1; height: 2px; background: var(--border-subtle); margin: 0 16px;"></div>

          <div class="wizard-step ${importStep === 4 ? 'active' : ''}" id="step-indicator-4" style="display: flex; align-items: center; gap: 10px; opacity: 0.5;">
            <div class="step-badge" style="width: 30px; height: 30px; border-radius: 50%; background: var(--bg-card-subtle); border: 1px solid var(--border-medium); color: var(--text-muted); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">4</div>
            <div>
              <div style="font-weight: 600; font-size: 13px;">Import Done</div>
              <div style="font-size: 11px; color: var(--text-muted);">Transactions saved</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Wizard Step Dynamic Container -->
      <div id="wizard-body">
        ${renderStep1Html()}
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
  attachStep1Listeners();
}

function renderStep1Html() {
  return `
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Step 1: Select Account & Upload Bank CSV</h3>
          <p>FinScope parses exports from Chase, Bank of America, Vietcombank, Techcombank, Revolut, etc.</p>
        </div>
      </div>

      <div style="display: flex; flex-direction: column; gap: 20px;">
        <div>
          <label class="form-label" style="font-weight: 600;">Destination Account *</label>
          <select id="import-account-select" class="form-select" style="width: 100%; max-width: 400px;">
            ${state.accounts.map(a => `<option value="${a.id}" ${a.id === selectedAccountId ? 'selected' : ''}>${escapeHtml(a.name)} (${escapeHtml(a.account_type)} - ${a.currency})</option>`).join('')}
          </select>
        </div>

        <!-- Dropzone -->
        <div id="csv-dropzone" style="border: 2px dashed var(--border-medium); border-radius: var(--radius-lg); padding: 40px 20px; text-align: center; cursor: pointer; transition: all 0.2s; background: var(--bg-card-subtle);">
          <i data-lucide="upload-cloud" style="width: 44px; height: 44px; color: var(--accent-blue); margin-bottom: 12px;"></i>
          <div style="font-weight: 600; font-size: 15px; margin-bottom: 6px;">Click or drag & drop CSV bank statement here</div>
          <div style="font-size: 12px; color: var(--text-muted);">Supports .csv, .txt with comma, semicolon, or tab delimiters</div>
          <input type="file" id="csv-file-input" accept=".csv, .txt" style="display: none;" />
        </div>

        <div style="text-align: center; font-size: 12px; color: var(--text-muted);">— OR PASTE RAW CSV CONTENT —</div>

        <div>
          <textarea id="csv-raw-textarea" class="form-input" rows="5" placeholder="Date,Amount,Payee,Description&#10;2026-09-01,-45.50,Supermarket,Weekly groceries" style="width: 100%; font-family: monospace; font-size: 12.5px;"></textarea>
        </div>

        <div style="display: flex; justify-content: flex-end; margin-top: 10px;">
          <button id="btn-goto-step2" class="btn btn-primary" style="min-width: 140px;">
            Continue to Mapping <i data-lucide="arrow-right"></i>
          </button>
        </div>
      </div>
    </div>
  `;
}

function attachStep1Listeners() {
  const dropzone = document.getElementById('csv-dropzone');
  const fileInput = document.getElementById('csv-file-input');
  const textarea = document.getElementById('csv-raw-textarea');
  const accountSelect = document.getElementById('import-account-select');
  const continueBtn = document.getElementById('btn-goto-step2');

  accountSelect?.addEventListener('change', (e) => {
    selectedAccountId = parseInt(e.target.value);
  });

  dropzone?.addEventListener('click', () => fileInput?.click());

  dropzone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = 'var(--accent-blue)';
    dropzone.style.background = 'rgba(91, 140, 255, 0.05)';
  });

  dropzone?.addEventListener('dragleave', () => {
    dropzone.style.borderColor = 'var(--border-medium)';
    dropzone.style.background = 'var(--bg-card-subtle)';
  });

  dropzone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = 'var(--border-medium)';
    dropzone.style.background = 'var(--bg-card-subtle)';
    if (e.dataTransfer.files.length > 0) {
      readFile(e.dataTransfer.files[0]);
    }
  });

  fileInput?.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      readFile(e.target.files[0]);
    }
  });

  function readFile(file) {
    const reader = new FileReader();
    reader.onload = (evt) => {
      rawCsvText = evt.target.result;
      if (textarea) textarea.value = rawCsvText.slice(0, 500) + (rawCsvText.length > 500 ? '\n... (truncated display)' : '');
      showToast(`Loaded "${file.name}" (${(file.size / 1024).toFixed(1)} KB)`, 'success');
    };
    reader.readAsText(file);
  }

  continueBtn?.addEventListener('click', async () => {
    const content = rawCsvText || textarea?.value.trim();
    if (!content) {
      showToast('Please select a CSV file or paste content first', 'error');
      return;
    }
    rawCsvText = content;
    selectedAccountId = parseInt(accountSelect?.value) || state.accounts[0]?.id;

    try {
      showToast('Analyzing CSV structure...', 'info');
      const preview = await api.previewCsvImport(rawCsvText, {}, selectedAccountId);
      detectedHeaders = preview.headers;
      currentMapping = preview.mapping;
      previewData = preview;
      goToStep(2);
    } catch (err) {
      showToast(`Failed to parse CSV: ${err.message}`, 'error');
    }
  });
}

function renderStep2Html() {
  const headerOptions = (selected) => {
    return '<option value="">-- None / Auto --</option>' +
      detectedHeaders.map(h => `<option value="${escapeHtml(h)}" ${h === selected ? 'selected' : ''}>${escapeHtml(h)}</option>`).join('');
  };

  return `
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Step 2: Map CSV Columns</h3>
          <p>FinScope has auto-detected your bank columns. Verify or adjust the mappings below.</p>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div>
          <label class="form-label">Transaction Date Column *</label>
          <select id="map-date" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.date)}
          </select>
        </div>

        <div>
          <label class="form-label">Amount Column (Single Net Amount)</label>
          <select id="map-amount" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.amount)}
          </select>
        </div>

        <div>
          <label class="form-label">Debit / Outflow Column (Optional)</label>
          <select id="map-debit" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.debit)}
          </select>
        </div>

        <div>
          <label class="form-label">Credit / Inflow Column (Optional)</label>
          <select id="map-credit" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.credit)}
          </select>
        </div>

        <div>
          <label class="form-label">Merchant / Payee Column</label>
          <select id="map-payee" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.payee)}
          </select>
        </div>

        <div>
          <label class="form-label">Description / Memo Column</label>
          <select id="map-desc" class="form-select" style="width: 100%;">
            ${headerOptions(currentMapping.description)}
          </select>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 30px; border-top: 1px solid var(--border-subtle); padding-top: 20px;">
        <button id="btn-back-step1" class="btn btn-secondary">
          <i data-lucide="arrow-left"></i> Back
        </button>
        <button id="btn-goto-step3" class="btn btn-primary">
          Preview Transactions <i data-lucide="arrow-right"></i>
        </button>
      </div>
    </div>
  `;
}

function attachStep2Listeners() {
  document.getElementById('btn-back-step1')?.addEventListener('click', () => goToStep(1));

  document.getElementById('btn-goto-step3')?.addEventListener('click', async () => {
    currentMapping = {
      date: document.getElementById('map-date')?.value || '',
      amount: document.getElementById('map-amount')?.value || '',
      debit: document.getElementById('map-debit')?.value || '',
      credit: document.getElementById('map-credit')?.value || '',
      payee: document.getElementById('map-payee')?.value || '',
      description: document.getElementById('map-desc')?.value || ''
    };

    if (!currentMapping.date) {
      showToast('Date column is required', 'error');
      return;
    }
    if (!currentMapping.amount && !currentMapping.debit && !currentMapping.credit) {
      showToast('Either Amount or Debit/Credit column must be selected', 'error');
      return;
    }

    try {
      showToast('Validating rows & checking duplicates...', 'info');
      previewData = await api.previewCsvImport(rawCsvText, currentMapping, selectedAccountId);
      goToStep(3);
    } catch (err) {
      showToast(`Error preparing preview: ${err.message}`, 'error');
    }
  });
}

function renderStep3Html() {
  const rows = previewData?.preview_rows || [];
  const dups = previewData?.duplicate_count || 0;
  const valids = previewData?.valid_count || 0;
  const total = previewData?.total_rows || 0;

  return `
    <div class="fin-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <h3>Step 3: Verify Transactions & Duplicates</h3>
          <p>Found ${total} total rows. Previewing the first ${rows.length} records.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="tag-pill" style="background: rgba(77, 213, 165, 0.15); color: #4DD5A5; font-weight: 600;">
            ✓ ${valids} New Transactions
          </span>
          ${dups > 0 ? `
            <span class="tag-pill" style="background: rgba(255, 184, 77, 0.15); color: #FFB84D; font-weight: 600;">
              ⚠ ${dups} Suspected Duplicates
            </span>
          ` : ''}
        </div>
      </div>

      <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
        <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">
          <input type="checkbox" id="chk-skip-dupes" checked style="accent-color: var(--accent-blue); width: 16px; height: 16px;" />
          <b>Skip suspected duplicate transactions automatically</b>
        </label>
      </div>

      <div class="table-container" style="max-height: 420px; overflow-y: auto;">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Date</th>
              <th>Type</th>
              <th>Payee / Description</th>
              <th style="text-align: right;">Amount</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr style="${r.is_duplicate ? 'background: rgba(255, 184, 77, 0.05);' : ''}">
                <td>
                  ${r.is_duplicate
                    ? '<span class="tag-pill" style="background: rgba(255, 184, 77, 0.2); color: #FFB84D; font-size: 11px;">Duplicate</span>'
                    : '<span class="tag-pill" style="background: rgba(77, 213, 165, 0.15); color: #4DD5A5; font-size: 11px;">New</span>'
                  }
                </td>
                <td>${escapeHtml(r.date)}</td>
                <td>
                  <span class="delta-badge ${r.transaction_type === 'income' ? 'positive' : 'negative'}">
                    ${r.transaction_type}
                  </span>
                </td>
                <td>
                  <div style="font-weight: 600; font-size: 13px;">${escapeHtml(r.payee)}</div>
                  ${r.description && r.description !== r.payee ? `<div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(r.description)}</div>` : ''}
                </td>
                <td style="text-align: right; font-weight: 700; font-family: monospace;">
                  ${state.formatCurrency(r.amount)}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; border-top: 1px solid var(--border-subtle); padding-top: 18px;">
        <button id="btn-back-step2" class="btn btn-secondary">
          <i data-lucide="arrow-left"></i> Back to Mapping
        </button>
        <button id="btn-commit-import" class="btn btn-primary" style="background: var(--color-positive); border-color: var(--color-positive);">
          <i data-lucide="check"></i> Confirm & Import ${valids} Transactions
        </button>
      </div>
    </div>
  `;
}

function attachStep3Listeners() {
  document.getElementById('btn-back-step2')?.addEventListener('click', () => goToStep(2));

  document.getElementById('btn-commit-import')?.addEventListener('click', async () => {
    const deduplicate = document.getElementById('chk-skip-dupes')?.checked ?? true;
    const btn = document.getElementById('btn-commit-import');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = 'Importing...';
    }

    try {
      const res = await api.commitCsvImport(rawCsvText, currentMapping, selectedAccountId, deduplicate);
      goToStep(4, res);
      state.notify({ type: 'data_changed' });
    } catch (err) {
      showToast(`Import failed: ${err.message}`, 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="check"></i> Confirm & Import';
        if (window.lucide) window.lucide.createIcons();
      }
    }
  });
}

function renderStep4Html(result) {
  const count = result?.imported_count ?? 0;
  const skipped = result?.skipped_duplicates ?? 0;

  return `
    <div class="fin-card" style="text-align: center; padding: 48px 24px;">
      <div style="width: 64px; height: 64px; border-radius: 50%; background: rgba(77, 213, 165, 0.15); color: #4DD5A5; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 20px;">
        <i data-lucide="check-circle" style="width: 36px; height: 36px;"></i>
      </div>
      <h2 style="font-size: 22px; font-weight: 700; margin-bottom: 8px;">Bank CSV Import Completed!</h2>
      <p style="font-size: 14px; color: var(--text-secondary); max-width: 480px; margin: 0 auto 24px auto;">
        Successfully imported <b>${count}</b> transactions into your account.
        ${skipped > 0 ? `<br/><span style="color: var(--color-warning);">Skipped ${skipped} duplicate transactions automatically.</span>` : ''}
      </p>

      <div style="display: flex; justify-content: center; gap: 14px;">
        <a href="#transactions" class="btn btn-primary">
          <i data-lucide="list"></i> View Transactions
        </a>
        <button id="btn-import-another" class="btn btn-secondary">
          <i data-lucide="upload"></i> Import Another File
        </button>
      </div>
    </div>
  `;
}

function attachStep4Listeners() {
  document.getElementById('btn-import-another')?.addEventListener('click', () => {
    goToStep(1);
  });
}

function goToStep(step, extraData = null) {
  importStep = step;
  const wizardBody = document.getElementById('wizard-body');
  if (!wizardBody) return;

  // Update step badges
  for (let i = 1; i <= 4; i++) {
    const ind = document.getElementById(`step-indicator-${i}`);
    if (!ind) continue;
    if (i === step) {
      ind.style.opacity = '1';
      const badge = ind.querySelector('.step-badge');
      if (badge) {
        badge.style.background = 'var(--accent-blue)';
        badge.style.color = '#fff';
        badge.style.borderColor = 'transparent';
      }
    } else if (i < step) {
      ind.style.opacity = '0.9';
      const badge = ind.querySelector('.step-badge');
      if (badge) {
        badge.style.background = 'var(--color-positive)';
        badge.style.color = '#fff';
        badge.style.borderColor = 'transparent';
        badge.innerHTML = '✓';
      }
    } else {
      ind.style.opacity = '0.5';
      const badge = ind.querySelector('.step-badge');
      if (badge) {
        badge.style.background = 'var(--bg-card-subtle)';
        badge.style.color = 'var(--text-muted)';
        badge.style.borderColor = 'var(--border-medium)';
        badge.innerHTML = `${i}`;
      }
    }
  }

  if (step === 1) {
    wizardBody.innerHTML = renderStep1Html();
    attachStep1Listeners();
  } else if (step === 2) {
    wizardBody.innerHTML = renderStep2Html();
    attachStep2Listeners();
  } else if (step === 3) {
    wizardBody.innerHTML = renderStep3Html();
    attachStep3Listeners();
  } else if (step === 4) {
    wizardBody.innerHTML = renderStep4Html(extraData);
    attachStep4Listeners();
  }

  if (window.lucide) window.lucide.createIcons();
}
