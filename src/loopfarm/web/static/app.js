/**
 * loopfarm web — SSE, keyboard navigation, and API interactions.
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let focusedId = null;
  let allNodeIds = [];
  let focusIndex = -1;
  let cmdPaletteOpen = false;

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

  function collectNodeIds() {
    allNodeIds = $$('.tree-node').map(function (el) { return el.dataset.id; });
  }

  function ago(ts) {
    if (!ts) return '';
    var d = Math.floor(Date.now() / 1000) - ts;
    if (d < 60) return 'just now';
    if (d < 3600) return Math.floor(d / 60) + 'm ago';
    if (d < 86400) return Math.floor(d / 3600) + 'h ago';
    return Math.floor(d / 86400) + 'd ago';
  }

  // ---------------------------------------------------------------------------
  // SSE
  // ---------------------------------------------------------------------------

  function initSSE() {
    var indicator = $('#sse-indicator');
    var statusEl = $('#sse-status');
    if (!indicator) return;

    var rootFilter = window.__rootId ? '?root=' + window.__rootId : '';
    var es = new EventSource('/api/events' + rootFilter);

    es.onopen = function () {
      indicator.className = 'status-indicator';
      statusEl.textContent = 'connected';
    };

    es.onerror = function () {
      indicator.className = 'status-indicator disconnected';
      statusEl.textContent = 'disconnected';
    };

    es.addEventListener('heartbeat', function () {
      // Update status bar stats
      api('GET', '/api/status').then(function (data) {
        var s = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
        s('stat-roots', data.roots);
        s('stat-open', data.open);
        s('stat-ready', data.ready);
        s('stat-failed', data.failed);
      });
    });

    es.addEventListener('issue_created', function (e) {
      var data = JSON.parse(e.data);
      updateTreeNode(data);
    });

    es.addEventListener('issue_updated', function (e) {
      var data = JSON.parse(e.data);
      updateTreeNode(data);
      // If this is the focused node, refresh detail panel
      if (focusedId === data.id) {
        loadDetail(data.id);
      }
    });

    es.addEventListener('runner_step', function (e) {
      var data = JSON.parse(e.data);
      var el = $('#runner-status');
      if (el) el.textContent = data.status + ' step ' + data.step;
    });

    es.addEventListener('runner_done', function (e) {
      var data = JSON.parse(e.data);
      var el = $('#runner-status');
      if (el) el.textContent = 'done: ' + data.status;
    });

    // Initial stats fetch
    api('GET', '/api/status').then(function (data) {
      var s = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
      s('stat-roots', data.roots);
      s('stat-open', data.open);
      s('stat-ready', data.ready);
      s('stat-failed', data.failed);
    });
  }

  function updateTreeNode(data) {
    var node = document.querySelector('.tree-node[data-id="' + data.id + '"]');
    if (!node) return;
    node.dataset.status = data.status;

    // Update status icon
    var statusEl = node.querySelector('.tree-status');
    if (statusEl) {
      if (data.status === 'closed') {
        if (data.outcome === 'failure') {
          statusEl.className = 'tree-status tree-status-failure';
          statusEl.innerHTML = '&#x2715;';
        } else if (data.outcome === 'expanded') {
          statusEl.className = 'tree-status tree-status-expanded';
          statusEl.innerHTML = '&#x25CB;';
        } else {
          statusEl.className = 'tree-status tree-status-success';
          statusEl.innerHTML = '&#x2713;';
        }
      } else if (data.status === 'in_progress') {
        statusEl.className = 'tree-status tree-status-active';
        statusEl.innerHTML = '&#x25CF;';
      } else {
        statusEl.className = 'tree-status tree-status-open';
        statusEl.innerHTML = '&#x25CB;';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Tree Navigation & Focus
  // ---------------------------------------------------------------------------

  function focusNode(id) {
    // Remove previous focus
    $$('.tree-node.focused').forEach(function (el) { el.classList.remove('focused'); });

    if (!id) {
      focusedId = null;
      focusIndex = -1;
      closePanel();
      return;
    }

    var node = document.querySelector('.tree-node[data-id="' + id + '"]');
    if (!node) return;

    node.classList.add('focused');
    focusedId = id;
    focusIndex = allNodeIds.indexOf(id);

    // Scroll into view
    node.scrollIntoView({ block: 'nearest' });
  }

  function moveFocus(delta) {
    collectNodeIds();
    // Filter to visible nodes only
    var visible = allNodeIds.filter(function (id) {
      var el = document.querySelector('.tree-node[data-id="' + id + '"]');
      return el && el.offsetParent !== null;
    });
    if (visible.length === 0) return;

    var currentIdx = visible.indexOf(focusedId);
    var next = currentIdx + delta;
    if (next < 0) next = 0;
    if (next >= visible.length) next = visible.length - 1;
    focusNode(visible[next]);
  }

  // ---------------------------------------------------------------------------
  // Detail Panel
  // ---------------------------------------------------------------------------

  function openPanel() {
    var pane = $('#detail-pane');
    if (pane) pane.classList.add('open');
  }

  window.closePanel = function () {
    var pane = $('#detail-pane');
    if (pane) pane.classList.remove('open');
  };

  function loadDetail(id) {
    api('GET', '/api/issues/' + id).then(function (issue) {
      if (issue.error) return;

      $('#detail-title').value = issue.title;
      $('#detail-body').value = issue.body || '';

      // Metadata
      var meta = $('#detail-meta');
      meta.innerHTML = '';
      var fields = [
        ['status', issue.status],
        ['outcome', issue.outcome || '-'],
        ['priority', 'P' + issue.priority],
        ['id', issue.id],
        ['created', ago(issue.created_at)],
        ['updated', ago(issue.updated_at)],
      ];
      if (issue.execution_spec) {
        if (issue.execution_spec.role) fields.push(['role', issue.execution_spec.role]);
        if (issue.execution_spec.cli) fields.push(['cli', issue.execution_spec.cli]);
        if (issue.execution_spec.model) fields.push(['model', issue.execution_spec.model]);
      }
      fields.forEach(function (f) {
        var row = document.createElement('div');
        row.className = 'detail-meta-row';
        row.innerHTML = '<span class="detail-meta-label">' + f[0] + '</span><span class="detail-meta-value">' + f[1] + '</span>';
        meta.appendChild(row);
      });

      // Tags
      var tagsEl = $('#detail-tags');
      tagsEl.innerHTML = '';
      (issue.tags || []).forEach(function (tag) {
        var chip = document.createElement('span');
        chip.className = 'emes-tag emes-tag-sm';
        chip.textContent = tag;
        tagsEl.appendChild(chip);
      });

      // Deps
      var depsEl = $('#detail-deps');
      depsEl.innerHTML = '';
      (issue.deps || []).forEach(function (dep) {
        var div = document.createElement('div');
        div.className = 'emes-text-xs emes-mono';
        div.textContent = dep.type + ' → ' + dep.target;
        depsEl.appendChild(div);
      });

      // Actions
      var actionsEl = $('#detail-actions');
      actionsEl.innerHTML = '';
      if (issue.status !== 'closed') {
        var closeBtn = document.createElement('button');
        closeBtn.className = 'emes-btn-sm';
        closeBtn.textContent = 'close (success)';
        closeBtn.onclick = function () { closeIssue(id, 'success'); };
        actionsEl.appendChild(closeBtn);

        var failBtn = document.createElement('button');
        failBtn.className = 'emes-btn-sm';
        failBtn.textContent = 'close (failure)';
        failBtn.onclick = function () { closeIssue(id, 'failure'); };
        actionsEl.appendChild(failBtn);
      } else {
        var reopenBtn = document.createElement('button');
        reopenBtn.className = 'emes-btn-sm';
        reopenBtn.textContent = 'reopen';
        reopenBtn.onclick = function () { reopenIssue(id); };
        actionsEl.appendChild(reopenBtn);
      }

      // Load log
      loadLog(id);
      // Load forum
      loadForum(id);

      openPanel();
    });
  }

  function loadLog(id) {
    var logEl = $('#detail-log');
    logEl.innerHTML = '<span class="emes-text-xs" style="color:var(--emes-gray-400)">loading...</span>';
    api('GET', '/api/logs/' + id).then(function (lines) {
      if (!lines || lines.length === 0) {
        logEl.innerHTML = '<span class="emes-text-xs" style="color:var(--emes-gray-400)">no log</span>';
        return;
      }
      logEl.innerHTML = '';
      lines.forEach(function (line) {
        var div = document.createElement('div');
        div.style.borderBottom = '1px solid var(--emes-gray-100)';
        div.style.padding = '0.15rem 0';
        // Try to extract meaningful content
        if (typeof line === 'object') {
          div.textContent = JSON.stringify(line).substring(0, 200);
        } else {
          div.textContent = String(line).substring(0, 200);
        }
        logEl.appendChild(div);
      });
      logEl.scrollTop = logEl.scrollHeight;
    });
  }

  function loadForum(id) {
    var el = $('#detail-forum');
    el.innerHTML = '';
    api('GET', '/api/forum/issue:' + id).then(function (msgs) {
      if (!msgs || msgs.length === 0) {
        el.innerHTML = '<span class="emes-text-xs" style="color:var(--emes-gray-400)">no messages</span>';
        return;
      }
      msgs.forEach(function (msg) {
        var div = document.createElement('div');
        div.className = 'forum-msg';
        div.innerHTML = '<div class="forum-msg-author">' + (msg.author || 'system') + ' · ' + ago(msg.created_at) + '</div>'
          + '<div class="forum-msg-body">' + escapeHtml(msg.body || '').substring(0, 500) + '</div>';
        el.appendChild(div);
      });
    });
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  window.saveTitle = function () {
    if (!focusedId) return;
    var val = $('#detail-title').value.trim();
    if (!val) return;
    api('PATCH', '/api/issues/' + focusedId, { title: val });
    // Update tree inline
    var node = document.querySelector('.tree-node[data-id="' + focusedId + '"] .tree-title');
    if (node) node.textContent = val;
  };

  window.saveBody = function () {
    if (!focusedId) return;
    var val = $('#detail-body').value;
    api('PATCH', '/api/issues/' + focusedId, { body: val });
  };

  function closeIssue(id, outcome) {
    api('POST', '/api/issues/' + id + '/close', { outcome: outcome }).then(function () {
      loadDetail(id);
    });
  }

  function reopenIssue(id) {
    api('POST', '/api/issues/' + id + '/reopen').then(function () {
      loadDetail(id);
    });
  }

  window.postForumMessage = function () {
    if (!focusedId) return;
    var input = $('#forum-input');
    var msg = input.value.trim();
    if (!msg) return;
    api('POST', '/api/forum/issue:' + focusedId, { body: msg, author: 'web' }).then(function () {
      input.value = '';
      loadForum(focusedId);
    });
  };

  function createChild() {
    if (!focusedId) return;
    var title = prompt('New child issue title:');
    if (!title) return;
    api('POST', '/api/issues', { title: title, parent: focusedId }).then(function () {
      location.reload();
    });
  }

  function createSibling() {
    if (!focusedId) return;
    // Find parent of focused node
    var node = document.querySelector('.tree-node[data-id="' + focusedId + '"]');
    if (!node) return;
    var parentNode = node.parentElement && node.parentElement.closest('.tree-node');
    var parentId = parentNode ? parentNode.dataset.id : null;

    var title = prompt('New sibling issue title:');
    if (!title) return;
    var body = { title: title };
    if (parentId) body.parent = parentId;
    api('POST', '/api/issues', body).then(function () {
      location.reload();
    });
  }

  window.toggleNode = function (id) {
    var children = document.getElementById('children-' + id);
    if (!children) return;
    children.classList.toggle('collapsed');
    var node = document.querySelector('.tree-node[data-id="' + id + '"]');
    var toggle = node && node.querySelector('.tree-toggle');
    if (toggle) toggle.classList.toggle('expanded');
  };

  window.startRunner = function () {
    if (!window.__rootId) return;
    api('POST', '/api/runner/start', { root_id: window.__rootId }).then(function (data) {
      var el = $('#runner-status');
      if (el) el.textContent = data.error || 'running';
    });
  };

  window.pauseRunner = function () {
    api('POST', '/api/runner/pause').then(function () {
      var el = $('#runner-status');
      if (el) el.textContent = 'paused';
    });
  };

  // ---------------------------------------------------------------------------
  // Command Palette
  // ---------------------------------------------------------------------------

  function openCmdPalette() {
    if (cmdPaletteOpen) return;
    cmdPaletteOpen = true;

    var backdrop = document.createElement('div');
    backdrop.className = 'cmd-palette-backdrop';
    backdrop.id = 'cmd-palette-backdrop';
    backdrop.onclick = function (e) { if (e.target === backdrop) closeCmdPalette(); };

    var palette = document.createElement('div');
    palette.className = 'cmd-palette';

    var input = document.createElement('input');
    input.className = 'cmd-palette-input';
    input.placeholder = 'Search issues...';
    input.type = 'text';

    var results = document.createElement('div');
    results.className = 'cmd-palette-results';

    palette.appendChild(input);
    palette.appendChild(results);
    backdrop.appendChild(palette);
    document.body.appendChild(backdrop);

    input.focus();

    // Load all issues for search
    var allIssues = [];
    api('GET', '/api/issues').then(function (issues) {
      allIssues = issues;
      renderPaletteResults(results, issues, '');
    });

    input.oninput = function () {
      var q = input.value.toLowerCase();
      var filtered = allIssues.filter(function (i) {
        return i.title.toLowerCase().includes(q) || i.id.includes(q);
      });
      renderPaletteResults(results, filtered, q);
    };

    input.onkeydown = function (e) {
      if (e.key === 'Escape') { closeCmdPalette(); e.preventDefault(); }
      if (e.key === 'Enter') {
        var sel = results.querySelector('.cmd-palette-item.selected') || results.querySelector('.cmd-palette-item');
        if (sel) { sel.click(); e.preventDefault(); }
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        var items = Array.from(results.querySelectorAll('.cmd-palette-item'));
        var idx = items.findIndex(function (el) { return el.classList.contains('selected'); });
        items.forEach(function (el) { el.classList.remove('selected'); });
        if (e.key === 'ArrowDown') idx = Math.min(idx + 1, items.length - 1);
        else idx = Math.max(idx - 1, 0);
        if (items[idx]) { items[idx].classList.add('selected'); items[idx].scrollIntoView({ block: 'nearest' }); }
        e.preventDefault();
      }
    };
  }

  function renderPaletteResults(container, issues, query) {
    container.innerHTML = '';
    issues.slice(0, 30).forEach(function (issue, i) {
      var item = document.createElement('div');
      item.className = 'cmd-palette-item' + (i === 0 ? ' selected' : '');
      item.innerHTML = '<span>' + escapeHtml(issue.title) + '</span><span class="emes-mono">' + issue.id.substring(0, 16) + '</span>';
      item.onclick = function () {
        closeCmdPalette();
        // Navigate to the issue's root DAG
        var rootDep = (issue.deps || []).find(function (d) { return d.type === 'parent'; });
        // For now just focus the node if we're on an editor page, or navigate
        var treeNode = document.querySelector('.tree-node[data-id="' + issue.id + '"]');
        if (treeNode) {
          focusNode(issue.id);
          loadDetail(issue.id);
        } else {
          // Check if it's a root
          if ((issue.tags || []).indexOf('node:root') >= 0) {
            window.location.href = '/dag/' + issue.id;
          }
        }
      };
      container.appendChild(item);
    });
    if (issues.length === 0) {
      container.innerHTML = '<div style="padding:1rem;color:var(--emes-gray-500);text-align:center">No matches</div>';
    }
  }

  function closeCmdPalette() {
    var el = $('#cmd-palette-backdrop');
    if (el) el.remove();
    cmdPaletteOpen = false;
  }

  // ---------------------------------------------------------------------------
  // Keyboard Handler
  // ---------------------------------------------------------------------------

  function initKeyboard() {
    collectNodeIds();

    // Expand all toggles by default
    $$('.tree-toggle').forEach(function (el) { el.classList.add('expanded'); });

    document.addEventListener('keydown', function (e) {
      // Ignore if typing in an input/textarea
      var tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (cmdPaletteOpen) return;

      switch (e.key) {
        case 'j':
          moveFocus(1);
          e.preventDefault();
          break;
        case 'k':
          moveFocus(-1);
          e.preventDefault();
          break;
        case 'Enter':
          if (focusedId) { loadDetail(focusedId); }
          e.preventDefault();
          break;
        case 'Escape':
          closePanel();
          focusNode(null);
          e.preventDefault();
          break;
        case ' ':
          if (focusedId) { toggleNode(focusedId); collectNodeIds(); }
          e.preventDefault();
          break;
        case 'Tab':
          if (e.shiftKey) {
            // Shift+Tab: promote (not implemented inline — would need reparent)
          } else {
            createChild();
          }
          e.preventDefault();
          break;
        case 'n':
          createSibling();
          e.preventDefault();
          break;
        case 'e':
          if (focusedId) {
            openPanel();
            loadDetail(focusedId);
            setTimeout(function () { $('#detail-title').focus(); }, 100);
          }
          e.preventDefault();
          break;
        case 'x':
          if (focusedId) {
            var outcome = prompt('Outcome (success/failure/skipped):', 'success');
            if (outcome) closeIssue(focusedId, outcome);
          }
          e.preventDefault();
          break;
        case 'r':
          if (focusedId) { reopenIssue(focusedId); }
          e.preventDefault();
          break;
        case '1': case '2': case '3': case '4': case '5':
          if (focusedId) {
            api('PATCH', '/api/issues/' + focusedId, { priority: parseInt(e.key) });
          }
          e.preventDefault();
          break;
        case '/':
          openCmdPalette();
          e.preventDefault();
          break;
      }
    });

    // Click handler for tree rows
    $$('.tree-row').forEach(function (row) {
      row.addEventListener('click', function () {
        var node = row.closest('.tree-node');
        if (!node) return;
        var id = node.dataset.id;
        focusNode(id);
        loadDetail(id);
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initSSE();
      initKeyboard();
    });
  } else {
    initSSE();
    initKeyboard();
  }
})();
