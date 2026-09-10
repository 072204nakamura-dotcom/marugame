/* ============================================================
   選手タグ（店主の評価）バッジ – 全ページ共通
   ------------------------------------------------------------
   data/tags/racer_tags.json（毎朝 JST 4:50 に台帳から取り込み）を読んで、
   出走表の選手名（.pname / .bname）の横に小さなバッジを出す。
   ページ側のHTMLは触らない。venues.js が自動でこのファイルを読み込む。

   台帳の評価 → バッジ:
     攻め 4・5 → 「攻4」「攻5」（赤）   攻め 1・2 → 「消1」「消2」（灰）  3 は出さない
     ST   4・5 → 「早」                 ST   1・2 → 「遅」
     型          → 伸／足／壁／差／前／F慣（青）
     メモ        → バッジにカーソルを当てる／長押しで見える（title）。評価が無くメモだけなら「メモ」
   ============================================================ */
(function () {
  var src  = document.currentScript ? document.currentScript.getAttribute('src') : 'tags.js';
  var base = src.replace(/tags\.js.*$/, '');
  var TYPE = { '伸び型': '伸', '出足型': '足', '壁': '壁', '差し屋': '差', '前付け': '前', 'F慣れ': 'F慣' };

  var style = document.createElement('style');
  style.textContent =
    '.rtag{display:inline-block;margin-left:4px;padding:0 5px;border-radius:4px;font-size:12px;font-weight:700;' +
    'line-height:18px;vertical-align:middle;background:#E6EEF7;color:#1F4E79;border:1px solid #B9CCE3;white-space:nowrap}' +
    '.rtag.atk{background:#FBE9E7;color:#B8322A;border-color:#F0B8B2}' +
    '.rtag.off{background:#EEEDE8;color:#5A574E;border-color:#D8D4C8}' +
    '.rtag.memo{background:#FFF6D9;color:#7A5A00;border-color:#F0DE9E}';
  document.head.appendChild(style);

  function norm(s) { return (s || '').replace(/[\s　]/g, ''); }

  function badges(r) {
    var out = [];
    if (r.atk >= 4) out.push(['攻' + r.atk, 'atk']);
    else if (r.atk >= 1 && r.atk <= 2) out.push(['消' + r.atk, 'off']);
    if (r.st >= 4) out.push(['早', '']);
    else if (r.st >= 1 && r.st <= 2) out.push(['遅', 'off']);
    (r.types || []).forEach(function (t) { out.push([TYPE[t] || t, t === '前付け' || t === 'F慣れ' ? 'atk' : '']); });
    if (!out.length && r.memo) out.push(['メモ', 'memo']);
    return out;
  }

  var byName = null;   // 正規化した名前 -> [評価]

  function decorate() {
    if (!byName) return;
    var nodes = document.querySelectorAll('.pname:not([data-rtag]), .bname:not([data-rtag])');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      el.setAttribute('data-rtag', '1');
      var t = el.firstChild;
      while (t && t.nodeType !== 3) t = t.nextSibling;      // 最初のテキストノード＝選手名
      if (!t) continue;
      var hit = byName[norm(t.nodeValue)];
      if (!hit || hit.length !== 1) continue;                 // 同姓同名は付けない（誤爆防止）
      var r = hit[0], frag = document.createDocumentFragment();
      badges(r).forEach(function (b) {
        var s = document.createElement('span');
        s.className = 'rtag' + (b[1] ? ' ' + b[1] : '');
        s.textContent = b[0];
        if (r.memo) s.title = r.memo;
        frag.appendChild(s);
      });
      t.parentNode.insertBefore(frag, t.nextSibling);         // 名前の直後（級別表示の前）
    }
  }

  var url = base + 'data/tags/racer_tags.json?v=' + Math.floor(Date.now() / 3600000);
  fetch(url, { cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
    if (!d || !d.racers) return;
    byName = {};
    Object.keys(d.racers).forEach(function (regno) {
      var r = d.racers[regno], k = norm(r.name);
      if (!k) return;
      (byName[k] = byName[k] || []).push(r);
    });
    decorate();
    // 出走表は data.json を読んでから描くページが多いので、描き直しにも追随する
    new MutationObserver(function () { decorate(); }).observe(document.body, { childList: true, subtree: true });
  }).catch(function () {});
})();
