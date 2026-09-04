/**
 * FinScope Settings & Data Management Page
 * Currency preferences, Account Manager, Category Manager, LocalAppData storage health,
 * and WAL-safe backups/restore.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../utils.js';

let showArchivedAccounts = false;
let showArchivedCategories = false;

export async function renderSettingsPage(container) {
  container.innerHTML = `
    <div class="settings-view" style="max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px;">
      
      <!-- Currency & Localization Preferences Card -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Currency & Formatting Preferences</h3>
            <p>Customize primary currency code and display locale</p>
          </div>
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;">
          <div>
            <div style="font-weight: 600; font-size: 14px;">Display Currency</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
              Amounts across all dashboards, reports, and charts will format in this currency.
            </div>
          </div>

          <div style="min-width: 220px;">
            <select id="setting-currency-select" class="form-select" style="width: 100%;">
              <option value="USD">USD — US Dollar ($)</option>
              <option value="VND">VND — Vietnamese Đồng (₫)</option>
              <option value="AUD">AUD — Australian Dollar ($)</option>
              <option value="EUR">EUR — Euro (€)</option>
              <option value="GBP">GBP — British Pound (£)</option>
              <option value="JPY">JPY — Japanese Yen (¥)</option>
              <option value="SGD">SGD — Singapore Dollar ($)</option>
              <option value="CAD">CAD — Canadian Dollar ($)</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Account Management Card -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Account Manager</h3>
            <p>Configure bank accounts, credit cards, investment portfolios, and cash reserves</p>
          </div>
          <div style="display: flex; align-items: center; gap: 14px;">
            <label style="display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); cursor: pointer;">
              <input type="checkbox" id="chk-show-archived-accs" ${showArchivedAccounts ? 'checked' : ''} style="accent-color: var(--accent-blue);" />
              Show Archived
            </label>
            <button id="btn-add-account" class="btn btn-primary btn-sm">
              <i data-lucide="plus"></i> New Account
            </button>
          </div>
        </div>

        <div class="table-container">
          <table class="fin-table" id="accounts-manager-table">
            <thead>
              <tr>
                <th>Account Name</th>
                <th>Type</th>
                <th>Institution</th>
                <th>Currency</th>
                <th style="text-align: right;">Opening Balance</th>
                <th style="text-align: right;">Current Balance</th>
                <th>Status</th>
                <th style="text-align: right;">Actions</th>
              </tr>
            </thead>
            <tbody id="accounts-manager-body">
              <tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 20px;">Loading accounts...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Category Management Card -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Category Manager</h3>
            <p>Customize personal expense and income categorization hierarchy</p>
          </div>
          <div style="display: flex; align-items: center; gap: 14px;">
            <label style="display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); cursor: pointer;">
              <input type="checkbox" id="chk-show-archived-cats" ${showArchivedCategories ? 'checked' : ''} style="accent-color: var(--accent-blue);" />
              Show Archived
            </label>
            <button id="btn-add-category" class="btn btn-primary btn-sm">
              <i data-lucide="plus"></i> New Category
            </button>
          </div>
        </div>

        <div class="table-container">
          <table class="fin-table" id="categories-manager-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Type</th>
                <th>Color Indicator</th>
                <th>Status</th>
                <th style="text-align: right;">Actions</th>
              </tr>
            </thead>
            <tbody id="categories-manager-body">
              <tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">Loading categories...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Database Health & LocalAppData Storage Card -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Data & Storage Health</h3>
            <p>Private local SQLite database in LocalAppData (isolated from application code)</p>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="tag-pill" id="stat-integrity-pill" style="background: rgba(77, 213, 165, 0.15); color: #4DD5A5; font-weight: 600;">
              <i data-lucide="check-circle" style="width: 14px; height: 14px;"></i> Healthy
            </span>
            <button id="btn-open-data-dir" class="btn btn-secondary btn-sm" title="Open folder in File Explorer">
              <i data-lucide="folder-open"></i> Open Data Folder
            </button>
          </div>
        </div>

        <div class="grid-3col" style="margin-bottom: 20px;">
          <div style="padding: 14px; background: var(--bg-card-subtle); border-radius: var(--radius-md);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Database Size</div>
            <div id="stat-db-size" style="font-size: 18px; font-weight: 700; margin-top: 4px;">Loading...</div>
          </div>

          <div style="padding: 14px; background: var(--bg-card-subtle); border-radius: var(--radius-md);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Total Transactions</div>
            <div id="stat-tx-count" style="font-size: 18px; font-weight: 700; margin-top: 4px;">0</div>
          </div>

          <div style="padding: 14px; background: var(--bg-card-subtle); border-radius: var(--radius-md);">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Date Range</div>
            <div id="stat-date-range" style="font-size: 13px; font-weight: 600; margin-top: 6px; color: var(--text-secondary);">Loading...</div>
          </div>
        </div>

        <div style="font-size: 12px; color: var(--text-muted); word-break: break-all;">
          Storage Location: <code id="stat-db-path" style="color: var(--accent-cyan);">finance.db</code>
        </div>
      </div>

      <!-- Backup & Restore Management -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Verified Offline Backups (.financebackup)</h3>
            <p>Uses SQLite Connection.backup() for safe WAL flushing and integrity verification</p>
          </div>
          <button id="btn-create-backup" class="btn btn-primary">
            <i data-lucide="archive"></i> Backup Now
          </button>
        </div>

        <div class="table-container">
          <table class="fin-table" id="backups-table">
            <thead>
              <tr>
                <th>Backup Archive</th>
                <th>Created Date</th>
                <th>Size</th>
                <th style="text-align: right;">Action</th>
              </tr>
            </thead>
            <tbody id="backups-table-body">
              <tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 20px;">Loading backups...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Demo Data Seeder Card -->
      <div class="fin-card">
        <div class="card-header">
          <div class="card-title-wrap">
            <h3>Evaluation Demo Data</h3>
            <p>Opt-in realistic dataset spanning 4 months (salaries, rent, groceries, transfers, and refunds)</p>
          </div>
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div style="font-size: 13px; color: var(--text-secondary); max-width: 550px;">
            FinScope never overwrites your real data automatically. Click below to populate demo data for testing.
          </div>
          <button id="btn-seed-data" class="btn btn-secondary">
            <i data-lucide="sparkles"></i> Populate Demo Data
          </button>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  setupSettingsHandlers();
  await loadSettingsData();
}

function setupSettingsHandlers() {
  // Currency Selector
  const currSelect = document.getElementById('setting-currency-select');
  if (currSelect) {
    currSelect.value = state.currency || 'USD';
    currSelect.addEventListener('change', async (e) => {
      const previousCurrency = state.currency || 'USD';
      const newCurr = e.target.value;
      try {
        await state.setCurrency(newCurr);
        showToast(`Currency changed to ${newCurr}`, 'success');
        state.notify({ type: 'data_changed' });
      } catch (err) {
        currSelect.value = previousCurrency;
        showToast(err.message || 'Unable to change currency', 'error');
      }
    });
  }

  // Open Data Folder
  document.getElementById('btn-open-data-dir')?.addEventListener('click', async () => {
    try {
      await api.openDataDir();
      showToast('Opening data folder...', 'info');
    } catch (err) {
      showToast(`Could not open folder: ${err.message}`, 'error');
    }
  });

  // Create Backup
  document.getElementById('btn-create-backup')?.addEventListener('click', async () => {
    try {
      const res = await api.createBackup();
      showToast(`Backup verified & created: ${res.filename}`, 'success');
      loadSettingsData();
    } catch (err) {
      showToast(`Backup failed: ${err.message}`, 'error');
    }
  });

  // Seed Demo Data
  document.getElementById('btn-seed-data')?.addEventListener('click', async () => {
    if (confirm('Populate realistic 4-month demo dataset? This will append sample records to your database.')) {
      try {
        const res = await api.seedDemoData(false);
        await state.reloadMetadata({ notify: false });
        showToast(`Added ${res.transactions_count} demo transactions across ${res.accounts_count} accounts!`, 'success');
        state.notify({ type: 'data_changed' });
        loadSettingsData();
      } catch (err) {
        showToast(`Failed to seed data: ${err.message}`, 'error');
      }
    }
  });

  // Show Archived Toggles
  document.getElementById('chk-show-archived-accs')?.addEventListener('change', (e) => {
    showArchivedAccounts = e.target.checked;
    loadAccountsTable();
  });

  document.getElementById('chk-show-archived-cats')?.addEventListener('change', (e) => {
    showArchivedCategories = e.target.checked;
    loadCategoriesTable();
  });

  // Add Account Button
  document.getElementById('btn-add-account')?.addEventListener('click', () => {
    promptAccountModal();
  });

  // Add Category Button
  document.getElementById('btn-add-category')?.addEventListener('click', () => {
    promptCategoryModal();
  });
}

async function loadSettingsData() {
  try {
    const [health, backups] = await Promise.all([
      api.getStorageHealth(),
      api.listBackups()
    ]);

    document.getElementById('stat-db-size').textContent = health.db_size_formatted;
    document.getElementById('stat-tx-count').textContent = health.transaction_count.toLocaleString();
    document.getElementById('stat-date-range').textContent = health.date_range;
    document.getElementById('stat-db-path').textContent = health.db_path;

    const currSelect = document.getElementById('setting-currency-select');
    if (currSelect && state.currency) {
      currSelect.value = state.currency;
    }

    renderBackupsTable(backups);
    await Promise.all([loadAccountsTable(), loadCategoriesTable()]);
  } catch (err) {
    console.error('Failed to load settings data:', err);
    showToast('Failed to load storage info', 'error');
  }
}

async function loadAccountsTable() {
  const tbody = document.getElementById('accounts-manager-body');
  if (!tbody) return;

  try {
    const accs = await api.getAccounts(showArchivedAccounts);
    if (!accs || accs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 20px;">No accounts found.</td></tr>';
      return;
    }

    tbody.innerHTML = accs.map(a => {
      const isArchived = Boolean(a.is_archived);
      return `
        <tr style="${isArchived ? 'opacity: 0.6; background: rgba(0,0,0,0.1);' : ''}">
          <td style="font-weight: 600;">${escapeHtml(a.name)}</td>
          <td><span class="delta-badge neutral">${escapeHtml(a.account_type)}</span></td>
          <td style="color: var(--text-secondary);">${escapeHtml(a.institution || '—')}</td>
          <td style="font-family: monospace;">${escapeHtml(a.currency || 'USD')}</td>
          <td style="text-align: right; font-family: monospace;">${state.formatCurrency(a.opening_balance)}</td>
          <td style="text-align: right; font-weight: 700; font-family: monospace; color: ${Number(a.current_balance) >= 0 ? 'var(--color-positive)' : 'var(--color-negative)'};">
            ${state.formatCurrency(a.current_balance)}
          </td>
          <td>
            ${isArchived 
              ? '<span class="tag-pill" style="background: rgba(255,184,77,0.15); color: #FFB84D;">Archived</span>'
              : '<span class="tag-pill" style="background: rgba(77,213,165,0.15); color: #4DD5A5;">Active</span>'
            }
          </td>
          <td style="text-align: right;">
            <div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px;">
              <button class="btn btn-secondary btn-sm btn-edit-account" data-id="${a.id}" data-name="${escapeHtml(a.name)}" data-type="${escapeHtml(a.account_type)}" data-inst="${escapeHtml(a.institution || '')}" data-bal="${a.opening_balance}" data-curr="${escapeHtml(a.currency || 'USD')}">
                Edit
              </button>
              <button class="btn btn-secondary btn-sm btn-toggle-archive-account" data-id="${a.id}" data-archived="${isArchived ? '1' : '0'}">
                ${isArchived ? 'Restore' : 'Archive'}
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) window.lucide.createIcons({ root: tbody });

    tbody.querySelectorAll('.btn-edit-account').forEach(btn => {
      btn.addEventListener('click', () => {
        promptAccountModal({
          id: parseInt(btn.dataset.id),
          name: btn.dataset.name,
          account_type: btn.dataset.type,
          institution: btn.dataset.inst,
          opening_balance: parseFloat(btn.dataset.bal) || 0,
          currency: btn.dataset.curr
        });
      });
    });

    tbody.querySelectorAll('.btn-toggle-archive-account').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = parseInt(btn.dataset.id);
        const isArchived = btn.dataset.archived === '1';
        try {
          await api.updateAccount(id, { is_archived: isArchived ? 0 : 1 });
          showToast(`Account ${isArchived ? 'restored' : 'archived'} successfully`, 'success');
          await state.reloadMetadata({ notify: false });
          state.notify({ type: 'data_changed' });
          loadAccountsTable();
        } catch (err) {
          showToast(`Action failed: ${err.message}`, 'error');
        }
      });
    });
  } catch (err) {
    console.error('Failed to load accounts:', err);
  }
}

async function loadCategoriesTable() {
  const tbody = document.getElementById('categories-manager-body');
  if (!tbody) return;

  try {
    const cats = await api.getCategories(showArchivedCategories);
    if (!cats || cats.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No categories found.</td></tr>';
      return;
    }

    const hexRegex = /^#[0-9A-Fa-f]{6}$/;
    tbody.innerHTML = cats.map(c => {
      const isArchived = Boolean(c.is_archived);
      const rawColor = (c.color || '').trim();
      const catColor = hexRegex.test(rawColor) ? rawColor : '#5B8CFF';
      return `
        <tr style="${isArchived ? 'opacity: 0.6; background: rgba(0,0,0,0.1);' : ''}">
          <td>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 28px; height: 28px; border-radius: 6px; background: ${catColor}20; color: ${catColor}; display: flex; align-items: center; justify-content: center;">
                <i data-lucide="${escapeHtml(c.icon || 'tag')}" style="width: 14px; height: 14px;"></i>
              </div>
              <span style="font-weight: 600;">${escapeHtml(c.name)}</span>
            </div>
          </td>
          <td>
            <span class="delta-badge ${c.type === 'income' ? 'positive' : 'negative'}">
              ${escapeHtml(c.type)}
            </span>
          </td>
          <td>
            <div style="display: flex; align-items: center; gap: 6px;">
              <div style="width: 14px; height: 14px; border-radius: 50%; background: ${catColor}; border: 1px solid rgba(255,255,255,0.2);"></div>
              <span style="font-family: monospace; font-size: 11.5px; color: var(--text-secondary);">${catColor}</span>
            </div>
          </td>
          <td>
            ${isArchived 
              ? '<span class="tag-pill" style="background: rgba(255,184,77,0.15); color: #FFB84D;">Archived</span>'
              : '<span class="tag-pill" style="background: rgba(77,213,165,0.15); color: #4DD5A5;">Active</span>'
            }
          </td>
          <td style="text-align: right;">
            <div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px;">
              <button class="btn btn-secondary btn-sm btn-edit-category" data-id="${c.id}" data-name="${escapeHtml(c.name)}" data-type="${escapeHtml(c.type)}" data-icon="${escapeHtml(c.icon || 'tag')}" data-color="${escapeHtml(c.color || '#5B8CFF')}">
                Edit
              </button>
              <button class="btn btn-secondary btn-sm btn-toggle-archive-category" data-id="${c.id}" data-archived="${isArchived ? '1' : '0'}">
                ${isArchived ? 'Restore' : 'Archive'}
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) window.lucide.createIcons({ root: tbody });

    tbody.querySelectorAll('.btn-edit-category').forEach(btn => {
      btn.addEventListener('click', () => {
        promptCategoryModal({
          id: parseInt(btn.dataset.id),
          name: btn.dataset.name,
          type: btn.dataset.type,
          icon: btn.dataset.icon,
          color: btn.dataset.color
        });
      });
    });

    tbody.querySelectorAll('.btn-toggle-archive-category').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = parseInt(btn.dataset.id);
        const isArchived = btn.dataset.archived === '1';
        try {
          await api.updateCategory(id, { is_archived: isArchived ? 0 : 1 });
          showToast(`Category ${isArchived ? 'restored' : 'archived'} successfully`, 'success');
          await state.reloadMetadata({ notify: false });
          state.notify({ type: 'data_changed' });
          loadCategoriesTable();
        } catch (err) {
          showToast(`Action failed: ${err.message}`, 'error');
        }
      });
    });
  } catch (err) {
    console.error('Failed to load categories:', err);
  }
}

function promptAccountModal(account = null) {
  const isEdit = Boolean(account && account.id);
  const name = prompt(`${isEdit ? 'Edit' : 'Create'} Account Name:`, account?.name || '');
  if (name === null) return;
  if (!name.trim()) {
    showToast('Account name cannot be empty', 'error');
    return;
  }

  const type = prompt('Account Type (Everyday, Savings, Credit Card, Investment):', account?.account_type || 'Everyday');
  if (type === null) return;

  const institution = prompt('Financial Institution (e.g. Chase, Vietcombank):', account?.institution || '');
  if (institution === null) return;

  const balanceStr = prompt('Opening Balance ($):', String(account?.opening_balance ?? 0));
  if (balanceStr === null) return;
  const balance = parseFloat(balanceStr) || 0;

  (async () => {
    try {
      if (isEdit) {
        await api.updateAccount(account.id, {
          name: name.trim(),
          account_type: type.trim(),
          institution: institution.trim(),
          opening_balance: balance
        });
        showToast('Account updated successfully', 'success');
      } else {
        await api.createAccount({
          name: name.trim(),
          account_type: type.trim(),
          institution: institution.trim(),
          opening_balance: balance,
          currency: state.currency || 'USD'
        });
        showToast('Account created successfully', 'success');
      }
      await state.reloadMetadata({ notify: false });
      state.notify({ type: 'data_changed' });
      loadAccountsTable();
    } catch (err) {
      showToast(`Failed to save account: ${err.message}`, 'error');
    }
  })();
}

function promptCategoryModal(category = null) {
  const isEdit = Boolean(category && category.id);
  const name = prompt(`${isEdit ? 'Edit' : 'Create'} Category Name:`, category?.name || '');
  if (name === null) return;
  if (!name.trim()) {
    showToast('Category name cannot be empty', 'error');
    return;
  }

  const type = prompt('Category Type (expense or income):', category?.type || 'expense');
  if (type === null) return;

  const color = prompt('Color Hex Code (e.g. #5B8CFF, #FF6B8A, #4DD5A5):', category?.color || '#5B8CFF');
  if (color === null) return;
  const hexRegex = /^#[0-9A-Fa-f]{6}$/;
  if (!hexRegex.test(color.trim())) {
    showToast('Invalid color format. Please use #RRGGBB (e.g. #5B8CFF)', 'error');
    return;
  }

  (async () => {
    try {
      if (isEdit) {
        await api.updateCategory(category.id, {
          name: name.trim(),
          type: type.trim().toLowerCase(),
          color: color.trim()
        });
        showToast('Category updated successfully', 'success');
      } else {
        await api.createCategory({
          name: name.trim(),
          cat_type: type.trim().toLowerCase(),
          icon: 'tag',
          color: color.trim()
        });
        showToast('Category created successfully', 'success');
      }
      await state.reloadMetadata({ notify: false });
      state.notify({ type: 'data_changed' });
      loadCategoriesTable();
    } catch (err) {
      showToast(`Failed to save category: ${err.message}`, 'error');
    }
  })();
}

function renderBackupsTable(backups) {
  const tbody = document.getElementById('backups-table-body');
  if (!tbody) return;

  if (!backups || backups.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 24px;">No backups created yet. Click "Backup Now" above.</td></tr>';
    return;
  }

  tbody.innerHTML = backups.map(b => {
    const sizeKB = (b.size_bytes / 1024).toFixed(1);
    const dateFormatted = new Date(b.created_at).toLocaleString();
    const countInfo = b.transaction_count !== null ? `(${b.transaction_count} records)` : '';

    return `
      <tr>
        <td style="font-weight: 600;">
          <i data-lucide="file-archive" style="width: 14px; height: 14px; margin-right: 6px; color: var(--accent-blue);"></i>
          ${b.filename}
          <span style="font-size: 11px; color: var(--text-muted); font-weight: normal; margin-left: 6px;">${countInfo}</span>
        </td>
        <td style="color: var(--text-secondary); font-size: 12.5px;">${dateFormatted}</td>
        <td style="color: var(--text-muted); font-size: 12px;">${sizeKB} KB</td>
        <td style="text-align: right;">
          <button class="btn btn-secondary btn-sm btn-restore-backup" data-path="${b.filepath}">
            <i data-lucide="rotate-ccw"></i> Restore
          </button>
        </td>
      </tr>
    `;
  }).join('');

  if (window.lucide) window.lucide.createIcons({ root: tbody });

  tbody.querySelectorAll('.btn-restore-backup').forEach(btn => {
    btn.addEventListener('click', async () => {
      const path = btn.dataset.path;
      if (confirm('Restoring this backup will overwrite current database state. A safety backup will be created first. Proceed?')) {
        try {
          await api.restoreBackup(path);
          await state.reloadMetadata({ notify: false });
          showToast('Database restored successfully from backup!', 'success');
          state.notify({ type: 'database_restored' });
          state.notify({ type: 'data_changed' });
          loadSettingsData();
        } catch (err) {
          showToast(`Restore failed: ${err.message}`, 'error');
        }
      }
    });
  });
}
