/**
 * emes Design System v2.0.0
 * Interactive components and utilities
 *
 * Design Philosophy (US Graphics inspired):
 * - Expose state and inner workings
 * - Verbosity over opacity
 * - Performance is design
 * - Don't infantilize users
 */

(function (global) {
  'use strict';

  const emes = {
    version: '2.0.0',

    /**
     * Initialize all emes components on the page
     */
    init: function () {
      this.initTooltips();
      this.initCopyButtons();
      this.initTimestamps();
      this.initStatusBar();
      this.initColorscale();
    },

    /**
     * Tooltip system
     * Add data-tooltip="text" to any element
     */
    initTooltips: function () {
      let tooltip = document.getElementById('emes-tooltip');
      if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'emes-tooltip';
        tooltip.className = 'emes-tooltip';
        tooltip.style.cssText = `
          position: fixed;
          background: #000;
          color: #fff;
          padding: 0.4rem 0.6rem;
          font-size: 0.75rem;
          max-width: 300px;
          line-height: 1.4;
          pointer-events: none;
          opacity: 0;
          z-index: 9999;
          border: 2px solid #000;
          font-family: "Berkeley Mono", monospace;
          transition: opacity 0.1s ease;
          box-shadow: 2px 2px #bbb;
        `;
        document.body.appendChild(tooltip);
      }

      const showTooltip = function (e) {
        const text = e.target.dataset.tooltip;
        if (!text) return;
        tooltip.textContent = text;
        tooltip.style.opacity = '1';
        positionTooltip(e);
      };

      const hideTooltip = function () {
        tooltip.style.opacity = '0';
      };

      const positionTooltip = function (e) {
        const x = e.clientX + 12;
        const y = e.clientY + 12;
        const rect = tooltip.getBoundingClientRect();
        const maxX = window.innerWidth - rect.width - 12;
        const maxY = window.innerHeight - rect.height - 12;
        tooltip.style.left = Math.min(x, maxX) + 'px';
        tooltip.style.top = Math.min(y, maxY) + 'px';
      };

      document.querySelectorAll('[data-tooltip]').forEach(function (el) {
        el.addEventListener('mouseenter', showTooltip);
        el.addEventListener('mouseleave', hideTooltip);
        el.addEventListener('mousemove', positionTooltip);
      });
    },

    /**
     * Copy to clipboard buttons
     * Add data-copy="text" or data-copy-target="#selector"
     */
    initCopyButtons: function () {
      document.querySelectorAll('[data-copy], [data-copy-target]').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.preventDefault();
          let text;

          if (btn.dataset.copyTarget) {
            const target = document.querySelector(btn.dataset.copyTarget);
            text = target ? target.textContent : '';
          } else {
            text = btn.dataset.copy;
          }

          if (text) {
            navigator.clipboard.writeText(text).then(function () {
              btn.classList.add('copied');
              const originalText = btn.textContent;
              if (!btn.dataset.copyNoChange) {
                btn.textContent = 'COPIED';
              }
              setTimeout(function () {
                btn.classList.remove('copied');
                if (!btn.dataset.copyNoChange) {
                  btn.textContent = originalText;
                }
              }, 1500);
            });
          }
        });
      });
    },

    /**
     * Relative timestamp display
     * Add data-timestamp="ISO8601" to show relative time
     */
    initTimestamps: function () {
      const formatRelative = function (date) {
        const now = new Date();
        const diff = now - date;
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (seconds < 60) return 'just now';
        if (minutes < 60) return minutes + 'm ago';
        if (hours < 24) return hours + 'h ago';
        if (days < 7) return days + 'd ago';
        if (days < 30) return Math.floor(days / 7) + 'w ago';
        if (days < 365) return Math.floor(days / 30) + 'mo ago';
        return Math.floor(days / 365) + 'y ago';
      };

      const formatAbsolute = function (date) {
        return date.toISOString().replace('T', ' ').substring(0, 19);
      };

      const updateTimestamps = function () {
        document.querySelectorAll('[data-timestamp]').forEach(function (el) {
          const iso = el.dataset.timestamp;
          if (!iso) return;
          const date = new Date(iso);
          if (isNaN(date)) return;

          const relative = formatRelative(date);
          const absolute = formatAbsolute(date);

          // Check if dual display
          if (el.classList.contains('emes-timestamp-dual') || el.classList.contains('timestamp-dual')) {
            let relSpan = el.querySelector('.emes-timestamp-relative, .timestamp-relative');
            let absSpan = el.querySelector('.emes-timestamp-absolute, .timestamp-absolute');

            if (!relSpan) {
              relSpan = document.createElement('span');
              relSpan.className = 'emes-timestamp-relative timestamp-relative';
              el.appendChild(relSpan);
            }
            if (!absSpan) {
              absSpan = document.createElement('span');
              absSpan.className = 'emes-timestamp-absolute timestamp-absolute';
              el.appendChild(absSpan);
            }

            relSpan.textContent = relative;
            absSpan.textContent = absolute;
          } else {
            el.textContent = relative;
            el.title = absolute;
          }
        });
      };

      updateTimestamps();
      setInterval(updateTimestamps, 60000); // Update every minute
    },

    /**
     * Status bar connection indicator
     */
    initStatusBar: function () {
      const indicator = document.getElementById('emes-connection-indicator');
      const status = document.getElementById('emes-connection-status');
      if (!indicator || !status) return;

      const updateStatus = function (connected) {
        if (connected) {
          indicator.classList.remove('emes-status-error', 'emes-status-warning', 'disconnected', 'connecting');
          indicator.classList.add('emes-status-online');
          status.textContent = 'connected';
        } else {
          indicator.classList.remove('emes-status-online');
          indicator.classList.add('emes-status-error', 'disconnected');
          status.textContent = 'disconnected';
        }
      };

      window.addEventListener('online', function () { updateStatus(true); });
      window.addEventListener('offline', function () { updateStatus(false); });
      updateStatus(navigator.onLine);
    },

    /**
     * Initialize colorscale bar components
     */
    initColorscale: function () {
      document.querySelectorAll('.emes-colorscale[data-auto], .colorscale[data-auto]').forEach(function (el) {
        if (el.children.length > 0) return; // Already populated

        const colors = [
          'var(--emes-black)',
          'var(--emes-gray-800)',
          'var(--emes-gray-700)',
          'var(--emes-gray-600)',
          'var(--emes-gray-500)',
          'var(--emes-gray-300)',
          'var(--emes-gray-100)',
          'var(--emes-blue)',
          'var(--emes-gold)',
          'var(--emes-green)',
          'var(--emes-red)'
        ];

        colors.forEach(function (color) {
          const div = document.createElement('div');
          div.style.background = color;
          el.appendChild(div);
        });
      });
    },

    /**
     * Format bytes to human readable
     */
    formatBytes: function (bytes) {
      if (bytes === undefined || bytes === null) return '';
      if (bytes < 1024) return bytes + 'B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'K';
      if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + 'M';
      return (bytes / (1024 * 1024 * 1024)).toFixed(1) + 'G';
    },

    /**
     * Format numbers with separators
     */
    formatNumber: function (num) {
      if (num === undefined || num === null) return '';
      return num.toLocaleString('en-US');
    },

    /**
     * Format duration in ms to human readable
     */
    formatDuration: function (ms) {
      if (ms < 1000) return ms + 'ms';
      if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
      if (ms < 3600000) return (ms / 60000).toFixed(1) + 'm';
      return (ms / 3600000).toFixed(1) + 'h';
    },

    /**
     * Format a date to compact ISO format
     */
    formatDate: function (date) {
      if (typeof date === 'string') date = new Date(date);
      return date.toISOString().replace('T', ' ').substring(0, 19);
    },

    /**
     * Format relative time
     */
    formatRelative: function (date) {
      if (typeof date === 'string') date = new Date(date);
      const now = new Date();
      const diff = now - date;
      const seconds = Math.floor(diff / 1000);
      const minutes = Math.floor(seconds / 60);
      const hours = Math.floor(minutes / 60);
      const days = Math.floor(hours / 24);

      if (seconds < 60) return 'just now';
      if (minutes < 60) return minutes + 'm ago';
      if (hours < 24) return hours + 'h ago';
      if (days < 7) return days + 'd ago';
      if (days < 30) return Math.floor(days / 7) + 'w ago';
      if (days < 365) return Math.floor(days / 30) + 'mo ago';
      return Math.floor(days / 365) + 'y ago';
    },

    /**
     * Create a metric display element
     */
    createMetric: function (value, unit, label) {
      const wrapper = document.createElement('div');
      wrapper.className = 'emes-metric metric';

      const valueEl = document.createElement('span');
      valueEl.className = 'emes-metric-value metric-value';
      valueEl.textContent = value;
      wrapper.appendChild(valueEl);

      if (unit) {
        const unitEl = document.createElement('span');
        unitEl.className = 'emes-metric-unit metric-unit';
        unitEl.textContent = unit;
        wrapper.appendChild(unitEl);
      }

      if (label) {
        const labelEl = document.createElement('span');
        labelEl.className = 'emes-metric-label metric-label';
        labelEl.textContent = label;
        wrapper.appendChild(labelEl);
      }

      return wrapper;
    },

    /**
     * Create a SKU/badge element
     */
    createSku: function (text, variant) {
      const sku = document.createElement('span');
      sku.className = 'emes-sku sku';
      if (variant) {
        sku.classList.add('emes-sku-' + variant);
        sku.classList.add('sku-' + variant);
      }
      sku.textContent = text;
      return sku;
    },

    /**
     * Create a button element
     */
    createButton: function (text, options) {
      options = options || {};
      const btn = document.createElement(options.href ? 'a' : 'button');

      if (options.nav) {
        btn.className = 'emes-btn-nav btn-nav';
      } else if (options.brutal) {
        btn.className = 'btn-brutal';
      } else {
        btn.className = 'emes-btn btn-classic';
      }

      if (options.primary) btn.classList.add('emes-btn-primary', 'btn-brutal-primary');
      if (options.green) btn.classList.add('emes-btn-green', 'btn-brutal-green');
      if (options.small) btn.classList.add('emes-btn-sm', 'btn-brutal-sm');
      if (options.className) btn.classList.add(options.className);

      if (options.href) btn.href = options.href;
      if (options.onClick) btn.addEventListener('click', options.onClick);

      btn.textContent = text;
      return btn;
    },

    /**
     * Create a box with label
     */
    createBox: function (label, content) {
      const box = document.createElement('div');
      box.className = 'emes-box box';
      if (label) box.dataset.label = label;

      if (typeof content === 'string') {
        box.innerHTML = content;
      } else if (content instanceof HTMLElement) {
        box.appendChild(content);
      }

      return box;
    },

    /**
     * Create a card element
     */
    createCard: function (options) {
      const card = document.createElement(options.href ? 'a' : 'div');
      card.className = 'emes-card card-brutal';
      if (options.href) card.href = options.href;

      if (options.title || options.badge) {
        const header = document.createElement('div');
        header.className = 'emes-card-header card-brutal-header';

        if (options.title) {
          const title = document.createElement('span');
          title.className = 'emes-card-title card-brutal-title';
          title.textContent = options.title;
          header.appendChild(title);
        }

        if (options.badge) {
          const badge = document.createElement('span');
          badge.className = 'emes-sku sku badge-brutal';
          badge.textContent = options.badge;
          header.appendChild(badge);
        }

        card.appendChild(header);
      }

      if (options.description) {
        const desc = document.createElement('p');
        desc.className = 'emes-card-desc card-brutal-desc';
        desc.textContent = options.description;
        card.appendChild(desc);
      }

      if (options.cta) {
        const cta = document.createElement('span');
        cta.className = 'emes-card-cta';
        cta.textContent = options.cta;
        card.appendChild(cta);
      }

      return card;
    },

    /**
     * Create a tag element
     */
    createTag: function (text, options) {
      options = options || {};
      const tag = document.createElement('span');
      tag.className = 'emes-tag';
      if (options.small) tag.classList.add('emes-tag-sm');
      if (options.active) tag.classList.add('active', 'emes-tag-active');
      tag.textContent = text;
      if (options.onClick) tag.addEventListener('click', options.onClick);
      return tag;
    },

    /**
     * Create a priority badge
     */
    createPriority: function (level) {
      const badge = document.createElement('span');
      badge.className = 'emes-priority priority-' + level;
      badge.textContent = 'P' + level;
      return badge;
    },

    /**
     * Create a status indicator
     */
    createStatusIndicator: function (status) {
      const indicator = document.createElement('span');
      indicator.className = 'emes-status-indicator status-indicator';
      if (status === 'online' || status === 'connected') {
        indicator.classList.add('emes-status-online');
      } else if (status === 'offline' || status === 'disconnected') {
        indicator.classList.add('emes-status-offline', 'disconnected');
      } else if (status === 'warning') {
        indicator.classList.add('emes-status-warning');
      } else if (status === 'error') {
        indicator.classList.add('emes-status-error');
      }
      return indicator;
    },

    /**
     * Create a progress bar
     */
    createProgressBar: function (percent, color) {
      const bar = document.createElement('div');
      bar.className = 'progress-brutal';

      const fill = document.createElement('div');
      fill.className = 'progress-brutal-fill';
      if (color) fill.classList.add(color);
      fill.style.width = Math.min(100, Math.max(0, percent)) + '%';

      bar.appendChild(fill);
      return bar;
    },

    /**
     * Create a colorscale bar
     */
    createColorscale: function () {
      const bar = document.createElement('div');
      bar.className = 'emes-colorscale colorscale';

      const colors = [
        'var(--emes-black)',
        'var(--emes-gray-800)',
        'var(--emes-gray-700)',
        'var(--emes-gray-600)',
        'var(--emes-gray-500)',
        'var(--emes-gray-300)',
        'var(--emes-gray-100)',
        'var(--emes-blue)',
        'var(--emes-gold)',
        'var(--emes-green)',
        'var(--emes-red)'
      ];

      colors.forEach(function (color) {
        const div = document.createElement('div');
        div.style.background = color;
        bar.appendChild(div);
      });

      return bar;
    },

    /**
     * Create a query metadata panel
     */
    createQueryMeta: function (items) {
      const panel = document.createElement('div');
      panel.className = 'emes-query-meta query-meta';

      items.forEach(function (item) {
        const itemEl = document.createElement('div');
        itemEl.className = 'emes-query-meta-item query-meta-item';

        const label = document.createElement('span');
        label.className = 'emes-query-meta-label query-meta-label';
        label.textContent = item.label;

        const value = document.createElement('span');
        value.className = 'emes-query-meta-value query-meta-value';
        value.textContent = item.value;

        itemEl.appendChild(label);
        itemEl.appendChild(value);
        panel.appendChild(itemEl);
      });

      return panel;
    },

    /**
     * Flash a message to the user
     */
    flash: function (message, type) {
      type = type || 'info';
      let container = document.getElementById('emes-flash-container');

      if (!container) {
        container = document.createElement('div');
        container.id = 'emes-flash-container';
        container.style.cssText = `
          position: fixed;
          top: 1rem;
          right: 1rem;
          z-index: 9999;
          max-width: 400px;
        `;
        document.body.appendChild(container);
      }

      const flash = document.createElement('div');
      flash.className = 'emes-box box emes-box-shadow box-shadow';
      flash.style.cssText = `
        margin-bottom: 0.5rem;
        padding: 0.75rem 1rem;
        animation: emes-slide-in 0.2s ease;
      `;

      if (type === 'error') {
        flash.style.borderColor = '#e7040f';
        flash.style.background = '#fef2f2';
      } else if (type === 'success') {
        flash.style.background = '#00794c';
        flash.style.color = '#fff';
      } else if (type === 'warning') {
        flash.style.background = '#ffb700';
        flash.style.color = '#000';
      }

      flash.textContent = message;
      container.appendChild(flash);

      setTimeout(function () {
        flash.style.opacity = '0';
        flash.style.transition = 'opacity 0.2s ease';
        setTimeout(function () {
          flash.remove();
        }, 200);
      }, 5000);
    },

    /**
     * Create a timestamp element
     */
    createTimestamp: function (date, dual) {
      if (typeof date === 'string') date = new Date(date);

      const el = document.createElement('span');
      el.className = dual ? 'emes-timestamp-dual timestamp-dual' : 'emes-timestamp timestamp';
      el.dataset.timestamp = date.toISOString();

      if (dual) {
        const relSpan = document.createElement('span');
        relSpan.className = 'emes-timestamp-relative timestamp-relative';
        relSpan.textContent = this.formatRelative(date);

        const absSpan = document.createElement('span');
        absSpan.className = 'emes-timestamp-absolute timestamp-absolute';
        absSpan.textContent = this.formatDate(date);

        el.appendChild(relSpan);
        el.appendChild(absSpan);
      } else {
        el.textContent = this.formatRelative(date);
        el.title = this.formatDate(date);
      }

      return el;
    }
  };

  // Add slide-in animation
  const style = document.createElement('style');
  style.textContent = `
    @keyframes emes-slide-in {
      from {
        transform: translateX(100%);
        opacity: 0;
      }
      to {
        transform: translateX(0);
        opacity: 1;
      }
    }
  `;
  document.head.appendChild(style);

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      emes.init();
    });
  } else {
    emes.init();
  }

  // Expose globally
  global.emes = emes;

})(typeof window !== 'undefined' ? window : this);
