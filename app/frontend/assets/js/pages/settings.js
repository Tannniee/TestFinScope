/**
 * FinScope Settings & Data Management Page
 * Currency preferences, LocalAppData storage health, WAL-safe backups, and restore snapshots
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../components/toast.js';

export async function renderSettingsPage(container) {
  container.innerHTML = `
    <div class="settings-view" style="max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px;">
      
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
      const newCurr = e.target.value;
      await state.setCurrency(newCurr);
      showToast(`Currency changed to ${newCurr}`, 'success');
      state.notify({ type: 'data_changed' });
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
    if (confirm('This will populate realistic transactions for current and prior 3 months. Continue?')) {
      try {
        await api.seedDemoData(true);
        showToast('Sample demo data generated successfully!', 'success');
        state.notify({ type: 'data_changed' });
        loadSettingsData();
      } catch (err) {
        showToast(`Failed to seed data: ${err.message}`, 'error');
      }
    }
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
  } catch (err) {
    console.error('Failed to load settings data:', err);
    showToast('Failed to load storage info', 'error');
  }
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
          showToast('Database restored successfully from backup!', 'success');
          state.notify({ type: 'data_changed' });
          loadSettingsData();
        } catch (err) {
          showToast(`Restore failed: ${err.message}`, 'error');
        }
      }
    });
  });
}
