/**
 * FinScope Mini Visuals: Sparklines & Radial Progress Gauges
 * Lightweight ECharts instances for KPI cards and summary banners.
 */

import { hexToRgba } from './chart-theme.js';

// Cache for chart instances keyed by element ID or WeakMap
const instanceMap = new WeakMap();

/**
 * Renders a lightweight sparkline inside domEl
 * @param {HTMLElement} domEl
 * @param {Array<number>} values
 * @param {string} colorHex - e.g. '#4DD5A5'
 * @param {Object} [options]
 */
export function renderSparkline(domEl, values, colorHex = '#5B8CFF', options = {}) {
  if (!domEl || !window.echarts || !Array.isArray(values) || values.length === 0) return null;

  // Clean up existing instance if already attached
  let instance = instanceMap.get(domEl);
  if (instance) {
    try { instance.dispose(); } catch (e) {}
  }

  instance = window.echarts.init(domEl);
  instanceMap.set(domEl, instance);

  const isLightOnGradient = options.lightOnGradient || false;
  const strokeColor = isLightOnGradient ? '#FFFFFF' : colorHex;
  const areaTopColor = isLightOnGradient ? 'rgba(255, 255, 255, 0.35)' : hexToRgba(colorHex, 0.30);
  const areaBottomColor = isLightOnGradient ? 'rgba(255, 255, 255, 0.0)' : hexToRgba(colorHex, 0.0);

  const option = {
    animation: true,
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: {
      left: 0,
      right: 0,
      top: 2,
      bottom: 2
    },
    xAxis: {
      type: 'category',
      show: false,
      boundaryGap: false,
      data: values.map((_, i) => i)
    },
    yAxis: {
      type: 'value',
      show: false,
      min: (value) => Math.min(0, value.min)
    },
    series: [
      {
        type: 'line',
        data: values,
        smooth: 0.35,
        showSymbol: false,
        lineStyle: {
          color: strokeColor,
          width: options.lineWidth || 2
        },
        areaStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: areaTopColor },
            { offset: 1, color: areaBottomColor }
          ])
        }
      }
    ]
  };

  instance.setOption(option, true);
  return instance;
}

/**
 * Renders a radial progress ring gauge inside domEl
 * @param {HTMLElement} domEl
 * @param {number} percent - 0 to 100+
 * @param {string} colorHex - e.g. '#C85AF4'
 * @param {Object} [options]
 */
export function renderRadialGauge(domEl, percent, colorHex = '#C85AF4', options = {}) {
  if (!domEl || !window.echarts) return null;

  let instance = instanceMap.get(domEl);
  if (instance) {
    try { instance.dispose(); } catch (e) {}
  }

  instance = window.echarts.init(domEl);
  instanceMap.set(domEl, instance);

  const clampedPct = Math.max(0, Math.min(100, Number(percent) || 0));
  const remainder = 100 - clampedPct;
  const trackColor = options.trackColor || 'rgba(255, 255, 255, 0.08)';

  const option = {
    animation: true,
    animationDuration: 900,
    animationEasing: 'cubicOut',
    series: [
      {
        type: 'pie',
        radius: options.radius || ['72%', '96%'],
        center: ['50%', '50%'],
        silent: true,
        startAngle: 90,
        clockwise: true,
        label: { show: false },
        data: [
          {
            value: clampedPct,
            itemStyle: {
              color: colorHex,
              borderRadius: 3
            }
          },
          {
            value: remainder,
            itemStyle: {
              color: trackColor
            }
          }
        ]
      }
    ]
  };

  instance.setOption(option, true);
  return instance;
}

/**
 * Disposes instance associated with domEl
 */
export function disposeChart(domEl) {
  if (!domEl) return;
  const instance = instanceMap.get(domEl);
  if (instance) {
    try { instance.dispose(); } catch (e) {}
    instanceMap.delete(domEl);
  }
}
