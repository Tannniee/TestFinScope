/**
 * FinScope Shared ECharts Design Theme & Helpers
 * Centralizes dark theme styles, tooltip formatting, and gradients.
 */

export const TOOLTIP_STYLE = {
  backgroundColor: '#171E33',
  borderColor: 'rgba(255, 255, 255, 0.1)',
  borderWidth: 1,
  padding: [10, 14],
  textStyle: {
    color: '#F5F7FB',
    fontSize: 12,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  },
  extraCssText: 'box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45); border-radius: 8px; backdrop-filter: blur(8px);'
};

export const AXIS_LABEL_STYLE = {
  color: '#66708A',
  fontSize: 11,
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
};

export const AXIS_LINE_STYLE = {
  lineStyle: { color: 'rgba(255, 255, 255, 0.1)' }
};

export const SPLIT_LINE_STYLE = {
  lineStyle: { color: 'rgba(255, 255, 255, 0.05)' }
};

export const GRID_TIGHT = {
  left: '3%',
  right: '3%',
  bottom: '3%',
  top: '14%',
  containLabel: true
};

export function hexToRgba(hex, alpha = 1) {
  if (!hex) return `rgba(255, 255, 255, ${alpha})`;
  if (hex.startsWith('rgba') || hex.startsWith('rgb')) return hex;
  let c = hex.replace('#', '');
  if (c.length === 3) {
    c = c.split('').map(x => x + x).join('');
  }
  const num = parseInt(c, 16);
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function verticalGradient(colorTop, colorBottom, opacityTop = 1, opacityBottom = 0) {
  if (!window.echarts) return colorTop;
  return new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: hexToRgba(colorTop, opacityTop) },
    { offset: 1, color: hexToRgba(colorBottom, opacityBottom) }
  ]);
}
