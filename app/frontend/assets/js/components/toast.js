/**
 * FinScope Toast Notification System
 */

export function showToast(message, type = 'success', duration = 3500, action = null) {
  if (message && (message.name === 'AbortError' || message === 'AbortError' || String(message).includes('AbortError') || String(message).includes('The user aborted a request'))) {
    return;
  }
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item ${type}`;

  const iconName = type === 'success' ? 'check-circle' : type === 'error' ? 'alert-circle' : 'info';
  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', iconName);
  const span = document.createElement('span');
  span.style.flex = '1';
  span.textContent = message;
  toast.appendChild(icon);
  toast.appendChild(span);

  if (action && action.label && action.onClick) {
    const actBtn = document.createElement('button');
    actBtn.type = 'button';
    actBtn.className = 'toast-action-btn';
    actBtn.textContent = action.label;
    actBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toast.remove();
      action.onClick();
    });
    toast.appendChild(actBtn);
  }

  container.appendChild(toast);

  if (window.lucide) {
    window.lucide.createIcons({ root: toast });
  }

  setTimeout(() => {
    toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 250);
  }, duration);
}
