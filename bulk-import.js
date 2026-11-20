/* Agent2API · 批量导入凭证插件
 *
 * 作用：把一堆 agent2api 账号 JSON 拖进来，自动识别每份凭证属于哪家 provider，
 *      分组预览后一次性 POST /api/accounts/import（同 provider+身份 会更新而非重复）。
 *
 * 依赖：同源静态脚本，运行在已登录的面板页面里，直接用 cookie 鉴权，不需要 token。
 * 安装：放到容器 /app/ui/bulk-import.js，并在 index.html 末尾加一行 script 标签。
 */
(function () {
  'use strict';

  var ACCEPT_HINT = '支持 .json 文件、多选拖拽，或直接粘贴数组/对象';

  // ---------- 厂商识别 ----------
  function detectProvider(o) {
    if (!o || typeof o !== 'object') return '';
    if (typeof o.provider === 'string' && o.provider.trim()) return o.provider.trim();

    var pid = String(o.pluginIdentity || '');
    if (pid.indexOf('codearts-') === 0) return 'codearts';
    if (pid.indexOf('trae-') === 0) return 'trae';

    // 特征字段
    if (o.security_token && o.domain_id) return 'codearts';
    if (o.devicePrivateKey && (o.enterpriseId || o.apiHost)) return 'trae';

    var host = String(o.apiHost || o.api_host || '').toLowerCase();
    if (host.indexOf('trae') >= 0) return 'trae';
    if (host.indexOf('huaweicloud') >= 0 || host.indexOf('codearts') >= 0) return 'codearts';
    if (host.indexOf('loomy') >= 0) return 'loomy';
    if (host.indexOf('workbuddy') >= 0) return 'workbuddy';
    return '';
  }

  // ---------- 把任意输入摊平成账号数组 ----------
  function flatten(parsed, out) {
    if (parsed == null) return;
    if (Array.isArray(parsed)) {
      parsed.forEach(function (x) { flatten(x, out); });
      return;
    }
    if (typeof parsed !== 'object') return;
    // 整库导出 / 带包装的结构
    if (Array.isArray(parsed.accounts)) { flatten(parsed.accounts, out); return; }
    if (Array.isArray(parsed.items)) { flatten(parsed.items, out); return; }
    if (parsed.packs) return;                       // 插件注册表，忽略

    // 单条凭证：有字典型特征才收
    var keys = Object.keys(parsed);
    if (keys.length && (parsed.provider || parsed.pluginIdentity || parsed.accessToken ||
        parsed.refreshToken || parsed.name || parsed.uid)) {
      var o = Object.assign({}, parsed);
      if (!o.format) o.format = 'agent2api-account';
      if (!o.provider) {
        var p = detectProvider(o);
        if (p) o.provider = p;
      }
      out.push(o);
    }
  }

  // ---------- 样式 ----------
  var css = '' +
    '.bi-card{margin:0 0 16px;padding:16px 18px;border:1px solid #2a2f3a;border-radius:12px;' +
    'background:#151922;display:flex;align-items:center;gap:14px;}' +
    '.bi-card .bi-card-t{flex:1;min-width:0;}' +
    '.bi-card .bi-card-t b{display:block;font-size:13.5px;margin-bottom:3px;}' +
    '.bi-card .bi-card-t span{color:#9ca3af;font-size:12px;}' +
    '.bi-card button{flex:none;padding:8px 15px;border-radius:8px;border:1px solid #6366f1;' +
    'background:#6366f1;color:#fff;font:600 12.5px system-ui,sans-serif;cursor:pointer;}' +
    '.bi-card button:hover{background:#4f46e5;}' +
    '.bi-mask{position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.55);display:flex;' +
    'align-items:center;justify-content:center;padding:24px;}' +
    '.bi-box{width:min(760px,96vw);max-height:88vh;overflow:auto;background:#12141a;color:#e5e7eb;' +
    'border:1px solid #2a2f3a;border-radius:14px;padding:20px;font:13px/1.6 system-ui,sans-serif;}' +
    '.bi-box h3{margin:0 0 6px;font-size:15px;}' +
    '.bi-box p.bi-sub{margin:0 0 14px;color:#9ca3af;font-size:12px;}' +
    '.bi-drop{border:1.5px dashed #3b4252;border-radius:10px;padding:18px;text-align:center;' +
    'color:#9ca3af;cursor:pointer;transition:.15s;}' +
    '.bi-drop.hot{border-color:#6366f1;color:#c7d2fe;background:rgba(99,102,241,.08);}' +
    '.bi-ta{width:100%;height:110px;margin-top:10px;background:#0b0d12;color:#d1d5db;' +
    'border:1px solid #2a2f3a;border-radius:8px;padding:9px;font:12px/1.5 ui-monospace,monospace;resize:vertical;}' +
    '.bi-prev{margin-top:12px;font-size:12px;}' +
    '.bi-tag{display:inline-block;margin:2px 6px 2px 0;padding:3px 9px;border-radius:999px;' +
    'background:#1f2937;color:#c7d2fe;font-size:11.5px;}' +
    '.bi-tag.bad{background:#3f1d1d;color:#fca5a5;}' +
    '.bi-row{display:flex;gap:8px;justify-content:flex-end;margin-top:16px;}' +
    '.bi-btn{padding:8px 15px;border-radius:8px;border:1px solid #2a2f3a;background:#1b1f27;' +
    'color:#e5e7eb;font:600 12.5px system-ui;cursor:pointer;}' +
    '.bi-btn.pri{background:#6366f1;border-color:#6366f1;color:#fff;}' +
    '.bi-btn:disabled{opacity:.45;cursor:not-allowed;}' +
    '.bi-out{margin-top:14px;padding:10px;border-radius:8px;background:#0b0d12;border:1px solid #2a2f3a;' +
    'font:12px/1.6 ui-monospace,monospace;white-space:pre-wrap;max-height:180px;overflow:auto;display:none;}';

  function injectCss() {
    if (document.getElementById('bi-style')) return;
    var s = document.createElement('style');
    s.id = 'bi-style';
    s.textContent = css;
    document.head.appendChild(s);
  }

  // ---------- 弹窗 ----------
  var state = { accounts: [] };

  function renderPreview(box) {
    var prev = box.querySelector('.bi-prev');
    var byProv = {};
    state.accounts.forEach(function (a) {
      var p = a.provider || '(未识别)';
      byProv[p] = (byProv[p] || 0) + 1;
    });
    var total = state.accounts.length;
    if (!total) { prev.innerHTML = ''; return; }
    var chips = Object.keys(byProv).sort().map(function (p) {
      var bad = p === '(未识别)' ? ' bad' : '';
      return '<span class="bi-tag' + bad + '">' + esc(p) + ' × ' + byProv[p] + '</span>';
    }).join('');
    prev.innerHTML = '<div style="color:#9ca3af;margin-bottom:6px">共识别 ' + total + ' 个账号：</div>' + chips;
    var btn = box.querySelector('.bi-btn.pri');
    if (btn) btn.disabled = total === 0;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c];
    });
  }

  function addText(box, text, name) {
    var parsed;
    try { parsed = JSON.parse(text); }
    catch (e) { return { ok: false, name: name, err: '不是合法 JSON' }; }
    var out = [];
    flatten(parsed, out);
    if (!out.length) return { ok: false, name: name, err: '未解析到账号' };
    state.accounts = state.accounts.concat(out);
    return { ok: true, name: name, n: out.length };
  }

  function openDialog() {
    injectCss();
    if (document.querySelector('.bi-mask')) return;

    var mask = document.createElement('div');
    mask.className = 'bi-mask';
    mask.innerHTML =
      '<div class="bi-box">' +
      '  <h3>批量导入凭证</h3>' +
      '  <p class="bi-sub">自动识别厂商（provider / pluginIdentity / 特征字段），同厂商同身份会更新原凭证。' + ACCEPT_HINT + '</p>' +
      '  <div class="bi-drop">点击选择 .json 文件（可多选），或把文件拖到这里</div>' +
      '  <input type="file" accept=".json,application/json" multiple style="display:none">' +
      '  <textarea class="bi-ta" placeholder="也可以直接把 JSON 数组 / 单个账号对象 / 整库导出内容粘贴到这里"></textarea>' +
      '  <div class="bi-row" style="justify-content:flex-start;margin-top:10px">' +
      '    <button class="bi-btn bi-add">解析粘贴内容</button>' +
      '    <button class="bi-btn bi-clear">清空</button>' +
      '  </div>' +
      '  <div class="bi-prev"></div>' +
      '  <div class="bi-out"></div>' +
      '  <div class="bi-row">' +
      '    <button class="bi-btn bi-cancel">关闭</button>' +
      '    <button class="bi-btn pri" disabled>导入</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(mask);

    var box = mask.querySelector('.bi-box');
    var drop = mask.querySelector('.bi-drop');
    var fileInput = mask.querySelector('input[type=file]');
    var ta = mask.querySelector('.bi-ta');
    var out = mask.querySelector('.bi-out');
    var btnImport = mask.querySelector('.bi-btn.pri');

    function say(msg) {
      out.style.display = 'block';
      out.textContent = String(msg);
    }

    async function takeFiles(files) {
      var msgs = [];
      for (var i = 0; i < files.length; i++) {
        var f = files[i];
        try {
          var t = await f.text();
          var r = addText(box, t, f.name);
          msgs.push(r.ok ? (f.name + '：' + r.n + ' 个') : (f.name + '：' + r.err));
        } catch (e) {
          msgs.push(f.name + '：读取失败');
        }
      }
      renderPreview(box);
      say(msgs.join('\n'));
    }

    drop.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () { takeFiles(fileInput.files); });
    ['dragenter', 'dragover'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('hot'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('hot'); });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files) takeFiles(e.dataTransfer.files);
    });

    mask.querySelector('.bi-add').addEventListener('click', function () {
      if (!ta.value.trim()) { say('先粘贴内容'); return; }
      var r = addText(box, ta.value, '粘贴内容');
      renderPreview(box);
      say(r.ok ? ('粘贴内容：' + r.n + ' 个') : ('粘贴内容：' + r.err));
    });

    mask.querySelector('.bi-clear').addEventListener('click', function () {
      state.accounts = [];
      ta.value = '';
      out.style.display = 'none';
      renderPreview(box);
    });

    mask.querySelector('.bi-cancel').addEventListener('click', function () { mask.remove(); });
    mask.addEventListener('click', function (e) { if (e.target === mask) mask.remove(); });

    btnImport.addEventListener('click', function () {
      if (!state.accounts.length) return;
      btnImport.disabled = true;
      say('正在导入 ' + state.accounts.length + ' 个账号…');
      // 服务端要求对象包裹：{"accounts":[ … ]}；裸数组会 400「导入内容必须是 JSON 对象」
      fetch('/api/accounts/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accounts: state.accounts })
      }).then(function (r) {
        return r.text().then(function (t) {
          var j;
          try { j = JSON.parse(t); } catch (e) { j = null; }
          if (!r.ok) {
            say('导入失败 HTTP ' + r.status + '\n' + (j && j.error ? JSON.stringify(j.error) : t.slice(0, 400)));
          } else {
            var d = (j && j.data) || j || {};
            say('导入完成\n' +
              '总计 ' + (d.total != null ? d.total : state.accounts.length) + '，' +
              '新增 ' + (d.added || 0) + '，更新 ' + (d.updated || 0) + '，' +
              '跳过 ' + (d.skipped || 0) + '，失败 ' + (d.failed || 0) +
              (d.errors && d.errors.length ? ('\n错误：' + JSON.stringify(d.errors).slice(0, 400)) : ''));
            state.accounts = [];
            renderPreview(box);
            if (window.wbApp && window.wbApp.refresh) { try { window.wbApp.refresh(); } catch (e) {} }
          }
        });
      }).catch(function (e) {
        say('请求异常：' + e);
      }).then(function () {
        btnImport.disabled = !state.accounts.length;
      });
    });
  }

  // ---------- 挂载：账号页「添加账号」右边的按钮 ----------
  var BTN_ID = 'btn-bulk-import';
  var ANCHOR = 'btn-add-account-2';

  function mountToolbarButton() {
    var anchor = document.getElementById(ANCHOR);
    if (!anchor || !anchor.parentNode) return;
    if (document.getElementById(BTN_ID)) return;
    var b = document.createElement('button');
    b.id = BTN_ID;
    b.type = 'button';
    b.textContent = '批量导入';
    b.title = '批量导入账号凭证（自动识别提供商）';
    b.className = anchor.className || '';
    b.addEventListener('click', openDialog);
    if (anchor.nextSibling) anchor.parentNode.insertBefore(b, anchor.nextSibling);
    else anchor.parentNode.appendChild(b);
  }

  function mount() {
    injectCss();
    mountToolbarButton();
  }

  // 面板是 React，重渲染会把按钮冲掉 —— 用观察器补回来（节流）
  var pending = false;
  function scheduleMount() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      mount();
    });
  }

  function boot() {
    mount();
    try {
      new MutationObserver(scheduleMount).observe(document.body, { childList: true, subtree: true });
    } catch (e) {
      // 极端情况下退化为定时补挂
      setInterval(scheduleMount, 1500);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();