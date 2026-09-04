/**
 * FinScope Calendar View Page
 * Interactive monthly matrix with daily cash flow badges & slide-out inspector
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { modals } from '../components/modals.js';
import { showToast } from '../components/toast.js';
import { escapeHtml, toLocalDateString } from '../utils.js';

let selectedDate = null;

export async function renderCalendarPage(container) {
  container.innerHTML = `
    <div class="calendar-view">
      <!-- Calendar Controls & Legend -->
      <div class="fin-card" style="margin-bottom: 20px; padding: 16px 22px;">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <h3 style="font-size: 16px; font-weight: 700;">${state.formatMonthLabel(state.month)}</h3>
            <span style="font-size: 12px; color: var(--text-muted);">Double-click any day to quickly record spending</span>
          </div>

          <!-- Legend -->
          <div style="display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--text-secondary);">
            <div style="display: flex; align-items: center; gap: 6px;">
              <span style="width: 10px; height: 10px; border-radius: 2px; background: #4DD5A5;"></span>
              <span>Income</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
              <span style="width: 10px; height: 10px; border-radius: 2px; background: #FF6B8A;"></span>
              <span>Expense</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Calendar Matrix -->
      <div class="fin-card" style="padding: 16px;">
        <div class="calendar-grid" style="margin-bottom: 8px;">
          <div class="calendar-weekday">Mon</div>
          <div class="calendar-weekday">Tue</div>
          <div class="calendar-weekday">Wed</div>
          <div class="calendar-weekday">Thu</div>
          <div class="calendar-weekday">Fri</div>
          <div class="calendar-weekday">Sat</div>
          <div class="calendar-weekday">Sun</div>
        </div>

        <div class="calendar-grid" id="calendar-cells-container">
          <div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;">
            Loading calendar...
          </div>
        </div>
      </div>

      <!-- Slide-out Day Inspector Drawer -->
      <div class="drawer-overlay" id="day-drawer-overlay"></div>
      <div class="drawer-panel" id="day-drawer-panel">
        <div class="drawer-header">
          <div>
            <h3 id="drawer-date-title" style="font-size: 16px; font-weight: 700;">Day Details</h3>
            <p id="drawer-date-subtitle" style="font-size: 12px; color: var(--text-muted);">Transactions overview</p>
          </div>
          <button id="drawer-close-btn" class="modal-close" style="background:none; border:none; cursor:pointer;">
            <i data-lucide="x"></i>
          </button>
        </div>

        <div class="drawer-body">
          <!-- Day Summary Box -->
          <div class="fin-card" style="background: var(--bg-card-subtle); padding: 16px;">
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; gap: 10px;">
              <div>
                <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Income</div>
                <div id="drawer-day-income" style="font-weight: 700; color: var(--color-positive); margin-top: 4px;">$0.00</div>
              </div>
              <div>
                <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Expense</div>
                <div id="drawer-day-expense" style="font-weight: 700; color: var(--color-negative); margin-top: 4px;">$0.00</div>
              </div>
              <div>
                <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Net</div>
                <div id="drawer-day-net" style="font-weight: 700; margin-top: 4px;">$0.00</div>
              </div>
            </div>
          </div>

          <div style="display: flex; align-items: center; justify-content: space-between;">
            <h4 style="font-size: 13px; font-weight: 600; text-transform: uppercase; color: var(--text-muted);">Transactions</h4>
            <button id="drawer-btn-add" class="btn btn-primary btn-sm">
              <i data-lucide="plus"></i> Add
            </button>
          </div>

          <div id="drawer-tx-list" style="display: flex; flex-direction: column; gap: 10px;">
            <div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">No transactions on this day.</div>
          </div>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();

  setupDrawerHandlers();
  await loadCalendar();
}

function setupDrawerHandlers() {
  const overlay = document.getElementById('day-drawer-overlay');
  const panel = document.getElementById('day-drawer-panel');
  const closeBtn = document.getElementById('drawer-close-btn');

  const closeDrawer = () => {
    overlay?.classList.remove('open');
    panel?.classList.remove('open');
  };

  closeBtn?.addEventListener('click', closeDrawer);
  overlay?.addEventListener('click', closeDrawer);

  document.getElementById('drawer-btn-add')?.addEventListener('click', () => {
    if (selectedDate) {
      modals.openTransactionModal(null, selectedDate);
    }
  });
}

async function loadCalendar() {
  try {
    const data = await api.getCalendarData(state.month, state.accountId);
    renderCalendarGrid(data.days);
  } catch (err) {
    console.error('Failed to load calendar data:', err);
    showToast('Failed to load calendar data', 'error');
  }
}

function renderCalendarGrid(daysMap) {
  const container = document.getElementById('calendar-cells-container');
  if (!container) return;

  const [y, m] = state.month.split('-').map(Number);
  const firstDayOfWeek = new Date(y, m - 1, 1).getDay(); // 0 is Sunday, 1 is Monday
  // Convert Sunday=0 to Monday=0 (0=Mon, 1=Tue... 6=Sun)
  const offset = (firstDayOfWeek + 6) % 7;
  const daysInMonth = new Date(y, m, 0).getDate();

  const todayStr = toLocalDateString();

  let html = '';

  // Previous month filler cells
  for (let i = 0; i < offset; i++) {
    html += '<div class="calendar-cell other-month"></div>';
  }

  // Days in month
  for (let day = 1; day <= daysInMonth; day++) {
    const dayStr = String(day).padStart(2, '0');
    const dateKey = `${state.month}-${dayStr}`;
    const dayData = daysMap[dateKey] || { income: 0, expense: 0, count: 0 };
    const isToday = dateKey === todayStr;

    // Heat intensity background based on expense
    let bgStyle = '';
    if (dayData.expense > 250) {
      bgStyle = 'background-color: rgba(255, 107, 138, 0.12); border-color: rgba(255, 107, 138, 0.3);';
    } else if (dayData.expense > 80) {
      bgStyle = 'background-color: rgba(255, 107, 138, 0.06);';
    }

    html += `
      <div class="calendar-cell ${isToday ? 'today' : ''}" data-date="${dateKey}" style="${bgStyle}">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span class="calendar-date-num">${day}</span>
          ${dayData.count > 0 ? `<span style="font-size: 10.5px; color: var(--text-muted);">${dayData.count} tx</span>` : ''}
        </div>

        <div class="calendar-amounts">
          ${dayData.income > 0 ? `
            <span style="color: var(--color-positive);">+${state.formatCurrency(dayData.income)}</span>
          ` : ''}
          ${dayData.expense > 0 ? `
            <span style="color: var(--color-negative);">-${state.formatCurrency(dayData.expense)}</span>
          ` : ''}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;

  // Add click & dblclick listeners
  container.querySelectorAll('.calendar-cell:not(.other-month)').forEach(cell => {
    cell.addEventListener('click', () => {
      openDayDrawer(cell.dataset.date);
    });

    cell.addEventListener('dblclick', () => {
      modals.openTransactionModal(null, cell.dataset.date);
    });
  });
}

async function openDayDrawer(dateStr) {
  selectedDate = dateStr;
  const overlay = document.getElementById('day-drawer-overlay');
  const panel = document.getElementById('day-drawer-panel');

  const titleEl = document.getElementById('drawer-date-title');
  const dObj = new Date(dateStr + 'T00:00:00');
  titleEl.textContent = dObj.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });

  overlay?.classList.add('open');
  panel?.classList.add('open');

  try {
    const res = await api.getTransactions({ start_date: dateStr, end_date: dateStr, limit: 100 });
    const txs = res.items;

    let totalIncome = 0;
    let totalExpense = 0;
    txs.forEach(t => {
      if (t.transaction_type === 'income') totalIncome += t.amount;
      if (t.transaction_type === 'expense') totalExpense += t.amount;
    });

    document.getElementById('drawer-day-income').textContent = `+${state.formatCurrency(totalIncome)}`;
    document.getElementById('drawer-day-expense').textContent = `-${state.formatCurrency(totalExpense)}`;

    const netVal = totalIncome - totalExpense;
    const netEl = document.getElementById('drawer-day-net');
    netEl.textContent = `${netVal >= 0 ? '+' : ''}${state.formatCurrency(netVal)}`;
    netEl.style.color = netVal >= 0 ? 'var(--color-positive)' : 'var(--color-negative)';

    const listEl = document.getElementById('drawer-tx-list');
    if (txs.length === 0) {
      listEl.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">No transactions recorded on this day.</div>';
      return;
    }

    listEl.innerHTML = txs.map(t => {
      const isIncome = t.transaction_type === 'income';
      const sign = isIncome ? '+' : '-';
      const color = isIncome ? 'var(--color-positive)' : 'var(--color-negative)';

      return `
        <div class="fin-card" style="padding: 14px; display: flex; align-items: center; justify-content: space-between;">
          <div>
            <div style="font-weight: 600; font-size: 13.5px;">${escapeHtml(t.merchant_name || t.description || 'Transaction')}</div>
            <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">
              ${escapeHtml(t.category_name || 'Uncategorized')} • ${escapeHtml(t.account_name || 'Everyday')} • ${escapeHtml(t.transaction_time || '')}
            </div>
          </div>
          <div style="font-weight: 700; color: ${color}; font-size: 14px;">
            ${sign}${state.formatCurrency(t.amount)}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load day transactions:', err);
    showToast('Failed to load day details', 'error');
  }
}
