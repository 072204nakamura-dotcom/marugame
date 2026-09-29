/* ============================================================
   買い目シグナル（kaime-live）— Google Apps Script
   ------------------------------------------------------------
   checkLive() … 5分おき。締切2〜9分前の候補レースについて
                 直前情報の風速とオッズを取り、買い目を確定して snapshots に保存
   settle()    … 毎朝6〜7時。前日以前の「成立」レースの結果・払戻を log に記入
   doGet()     … ページ用JSON（?date=YYYY-MM-DD ／ ?mode=summary）
   setup()     … 最初に1回だけ手で実行（シート3枚を作る）
   testParse() … 並びの確認。ログに ALL OK と出ればよい

   ★ ルールの条件・数値は scripts/kaime/rules.py（実装指示書 §3）と同じ。変えないこと。
   ★ 判定の関数は scripts/kaime/judge.py と同じ仕様。片方を直したらもう片方も直す。
   ★ コードを直したら「デプロイを管理 → 鉛筆 → 新バージョン → デプロイ」。
   ============================================================ */

var TARGETS_BASE = 'https://072204nakamura-dotcom.github.io/marugame/data/kaime/targets/';
var BOAT = 'https://www.boatrace.jp/owpc/pc/race/';
var TZ = 'Asia/Tokyo';
var SNAP_HEAD = ['date', 'jcd', 'race', 'rule_id', 'rank', 'judged_at', 'wind_m', 'wind_time', 'status',
                 'bets', 'points', 'stake', 'deadline', 'venue', 'note'];
var LOG_HEAD = ['date', 'jcd', 'race', 'rule_id', 'rank', 'points', 'stake', 'hit', 'payout',
                'final_combo', 'final_payout', 'judged_odds_of_hit', 'final_odds', 'venue'];

// ---- ルール表（rules.py と同じ）----------------------------------
var RULES = {
  'KIR-A': { rank: '◎', wind: true,  bet: '3t_X1Y_40_80_pop50', label: '3連単 X-1-Y（40〜80倍・50番人気まで）' },
  'KIR-B': { rank: '◎', wind: true,  bet: '2t_X1',              label: '2連単 X-1（5点）' },
  'KIR-C': { rank: '△', wind: true,  bet: '3t_X1Y_2to5_pop50',  label: '3連単 X-1-Y（X,Y∈2〜5・50番人気まで）' },
  'MIY-B': { rank: '△', wind: true,  bet: '2t_X1',              label: '2連単 X-1（5点）' },
  'FUK-B': { rank: '△', wind: true,  bet: '2t_X1',              label: '2連単 X-1（5点）' },
  'WAK-C': { rank: '△', wind: true,  bet: '3t_X1Y_all',         label: '3連単 X-1-Y（20点）' },
  'TOD-A': { rank: '△', wind: true,  bet: '3t_X1Y_40_80_pop50', label: '3連単 X-1-Y（40〜80倍・50番人気まで）' },
  'ASH-Q': { rank: '×', wind: false, bet: '3f_outer_top3',      label: '3連複 外上位3艇の1点' },
  'MAR-E': { rank: '×', wind: true,  bet: '2t_outer_top3_box',  label: '2連単 外上位3艇BOX（6点）' },
  'W1-Q':  { rank: '×', wind: false, bet: '3f_1XY_all',         label: '3連複 1号艇を含む10通り' }
};
var WIND_MIN = 5;
var FINAL_ODDS_RULES = { 'KIR-A': 1, 'TOD-A': 1 };   // 確定オッズも保存するルール（§6-4）
var OUTER = [2, 3, 4, 5, 6];

// ==================================================================
// 準備
// ==================================================================
function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();   // エディタから実行したときだけ使う（紐づいた表）
  PropertiesService.getScriptProperties().setProperty('SS_ID', ss.getId());
  makeSheet_(ss, 'snapshots', SNAP_HEAD);
  makeSheet_(ss, 'log', LOG_HEAD);
  var st = ss.getSheetByName('settings') || ss.insertSheet('settings');
  if (st.getLastRow() === 0) {
    st.getRange(1, 1, 2, 2).setValues([['key', 'value'], ['unit', '100']]);
  }
  var def = ss.getSheetByName('シート1');
  if (def && ss.getSheets().length > 3) ss.deleteSheet(def);
  Logger.log('setup 完了：snapshots / log / settings を用意しました（ID ' + ss.getId() + '）');
}

function makeSheet_(ss, name, head) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  sh.getRange(1, 1, sh.getMaxRows(), 26).setNumberFormat('@');   // 「2-1-5」や「01」を日付・数値に化けさせない
  if (sh.getLastRow() === 0) sh.getRange(1, 1, 1, head.length).setValues([head]);
  sh.setFrozenRows(1);
}

function book_() {
  var id = PropertiesService.getScriptProperties().getProperty('SS_ID');
  if (!id) throw new Error('先に setup を実行してください');
  return SpreadsheetApp.openById(id);
}

function unit_() {
  var v = book_().getSheetByName('settings').getRange('B2').getValue();
  return Number(v) > 0 ? Number(v) : 100;
}

// ==================================================================
// 取得・パース（judge.py と同じ仕様）
// ==================================================================
function fetch_(url) {
  for (var i = 0; i < 2; i++) {
    try {
      var r = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
      if (r.getResponseCode() === 200) return r.getContentText('UTF-8');
    } catch (e) { /* もう一度 */ }
    Utilities.sleep(2000);
  }
  return null;
}

var lastBoatFetch_ = 0;
function fetchBoat_(page, jcd, race, ymd) {
  var wait = 1100 - (Date.now() - lastBoatFetch_);       // 公式サイトへは1秒以上あける
  if (wait > 0) Utilities.sleep(wait);
  lastBoatFetch_ = Date.now();
  return fetch_(BOAT + page + '?rno=' + race + '&jcd=' + jcd + '&hd=' + ymd.replace(/-/g, ''));
}

function oddsVals_(html) {
  var re = /class="oddsPoint[^"]*">([^<]*)</g, m, out = [];
  while ((m = re.exec(html || '')) !== null) out.push(m[1]);
  return out;
}

function num_(v) {
  var x = parseFloat(String(v).trim());
  return (isNaN(x) || !/^[\d.]+$/.test(String(v).trim())) ? null : x;   // 欠場など
}

function parseOdds3t(html) {
  var v = oddsVals_(html);
  if (v.length < 120) return null;
  var out = {};
  for (var i = 0; i < 120; i++) {
    var r = Math.floor(i / 6), head = i % 6 + 1;
    var others = [1, 2, 3, 4, 5, 6].filter(function (b) { return b !== head; });
    var second = others[Math.floor(r / 4)];
    var thirds = others.filter(function (b) { return b !== second; });
    out[head + '-' + second + '-' + thirds[r % 4]] = num_(v[i]);
  }
  return out;
}

function parseOdds2tf(html) {
  var v = oddsVals_(html);
  if (v.length < 45) return null;
  var t2 = {}, f2 = {}, i;
  for (i = 0; i < 30; i++) {
    var r = Math.floor(i / 6), head = i % 6 + 1;
    var others = [1, 2, 3, 4, 5, 6].filter(function (b) { return b !== head; });
    t2[head + '-' + others[r]] = num_(v[i]);
  }
  i = 30;
  for (var b = 2; b <= 6; b++) for (var a = 1; a < b; a++) f2[a + '-' + b] = num_(v[i++]);
  return { t2: t2, f2: f2 };
}

function f3Order_() {
  var out = [];
  for (var b = 2; b <= 5; b++) for (var c = b + 1; c <= 6; c++) for (var a = 1; a < b; a++) out.push(a + '-' + b + '-' + c);
  return out;
}

function parseOdds3f(html) {
  var v = oddsVals_(html);
  if (v.length < 20) return null;
  var out = {}, ord = f3Order_();
  for (var i = 0; i < 20; i++) out[ord[i]] = num_(v[i]);
  return out;
}

function popularity_(o3t) {
  var nums = [], k;
  for (k in o3t) if (o3t[k] !== null) nums.push(o3t[k]);
  var out = {};
  for (k in o3t) {
    if (o3t[k] === null) { out[k] = null; continue; }
    var n = 1;
    for (var j = 0; j < nums.length; j++) if (nums[j] < o3t[k]) n++;
    out[k] = n;
  }
  return out;
}

function parseWind(html) {
  var m = /風速<\/span>\s*<span class="weather1_bodyUnitLabelData">(\d+)m/.exec(html || '');
  var t = /水面気象情報[\s　]*([^<]*?)\s*<\/p>/.exec(html || '');
  return { wind: m ? parseInt(m[1], 10) : null, time: t ? t[1] : '' };
}

// bet種別 → [{combo, odds, pop}]。オッズが要るのに無ければ null（保留）、該当ゼロなら []（見送り）
function buildBets(bet, race, o3t, o2t, o3f) {
  var pop = o3t ? popularity_(o3t) : {};
  function row(c, table, withPop) {
    return { combo: c, odds: table && table[c] !== undefined ? table[c] : null, pop: withPop ? pop[c] : null };
  }
  var out = [], x, y;
  if (bet.indexOf('3t_') === 0) {
    if (!o3t) return null;
    var xs = bet === '3t_X1Y_2to5_pop50' ? [2, 3, 4, 5] : OUTER;
    for (var i = 0; i < xs.length; i++) for (var j = 0; j < xs.length; j++) {
      x = xs[i]; y = xs[j];
      if (x === y) continue;
      var c = x + '-1-' + y, o = o3t[c], p = pop[c];
      if (bet === '3t_X1Y_all') out.push(row(c, o3t, true));
      else if (o === null || p === null) continue;
      else if (bet === '3t_X1Y_40_80_pop50' && o >= 40.0 && o < 80.0 && p <= 50) out.push(row(c, o3t, true));
      else if (bet === '3t_X1Y_2to5_pop50' && p <= 50) out.push(row(c, o3t, true));
    }
    return out;
  }
  if (bet === '2t_X1') {
    if (!o2t) return null;
    return OUTER.map(function (x) { return row(x + '-1', o2t, false); });
  }
  var t = race.outer_top3;
  if (bet === '2t_outer_top3_box') {
    if (!o2t) return null;
    t.forEach(function (a) { t.forEach(function (b) { if (a !== b) out.push(row(a + '-' + b, o2t, false)); }); });
    return out;
  }
  if (bet === '3f_outer_top3') {
    if (!o3f) return null;
    return [row(t.slice().sort().join('-'), o3f, false)];
  }
  if (bet === '3f_1XY_all') {
    if (!o3f) return null;
    OUTER.forEach(function (a) { OUTER.forEach(function (b) { if (a < b) out.push(row('1-' + a + '-' + b, o3f, false)); }); });
    return out;
  }
  throw new Error('unknown bet ' + bet);
}

// raceresult → {'3連単':[[組番,払戻]], '3連複':[...], '2連単':[...], henkan:[艇番], cancelled}。結果がまだ無ければ null
function parseResult(html) {
  html = html || '';
  var out = { henkan: [], cancelled: false };
  ['3連単', '3連複', '2連単'].forEach(function (kind) {
    var m = new RegExp('<td rowspan="2">' + kind + '</td>([\\s\\S]*?)</tbody>').exec(html), rows = [];
    if (m) {
      m[1].split('<tr').forEach(function (tr) {
        var nums = [], mm, re = /numberSet1_number[^>]*>(\d)</g;
        while ((mm = re.exec(tr)) !== null) nums.push(mm[1]);
        var pay = /is-payout1">&yen;([\d,]+)/.exec(tr);
        if (nums.length && pay) {
          if (kind === '3連複') nums.sort();
          rows.push([nums.join('-'), parseInt(pay[1].replace(/,/g, ''), 10)]);
        }
      });
    }
    out[kind] = rows;
  });
  var h = /<th>返還<\/th>([\s\S]*?)<\/table>/.exec(html);
  if (h) {
    var mm, re = /numberSet1_number[^>]*>(\d)</g;
    while ((mm = re.exec(h[1])) !== null) out.henkan.push(parseInt(mm[1], 10));
  }
  if (!out['3連単'].length) {
    if (html.indexOf('レース中止') >= 0) out.cancelled = true;
    else return null;
  }
  return out;
}

var KIND_OF_BET = { '3t': '3連単', '2t': '2連単', '3f': '3連複' };

function settleBets(bet, bets, res, unit) {
  if (res.cancelled) return { pay: unit * bets.length, hits: [] };
  var wins = {};
  res[KIND_OF_BET[bet.substr(0, 2)]].forEach(function (r) { wins[r[0]] = r[1]; });
  var pay = 0, hits = [];
  bets.forEach(function (b) {
    var boats = b.combo.split('-').map(Number);
    if (boats.some(function (x) { return res.henkan.indexOf(x) >= 0; })) pay += unit;
    else if (wins[b.combo] !== undefined) { pay += Math.floor(wins[b.combo] * unit / 100); hits.push(b.combo); }
  });
  return { pay: pay, hits: hits };
}

// ==================================================================
// 候補JSON
// ==================================================================
function today_() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'); }

function getTargets_(date) {
  var cache = CacheService.getScriptCache(), key = 'targets_' + date;
  var hit = cache.get(key);
  if (hit) return JSON.parse(hit);
  var txt = fetch_(TARGETS_BASE + date + '.json?t=' + Date.now());
  if (!txt) return null;
  var obj;
  try { obj = JSON.parse(txt); } catch (e) { return null; }
  if (obj.date !== date) return null;
  if (txt.length < 90000) cache.put(key, txt, 600);   // 10分キャッシュ（朝の更新が遅れても10分で拾う）
  return obj;
}

function deadlineMs_(date, hhmm) {
  return new Date(date + 'T' + hhmm + ':00+09:00').getTime();
}

// ==================================================================
// checkLive（5分おき）
// ==================================================================
function checkLive() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;               // 前回がまだ動いていたら今回は休む
  try {
    var date = today_();
    var tg = getTargets_(date);
    if (!tg || !tg.races || !tg.races.length) return;
    var now = Date.now(), unit = unit_();
    tg.races.forEach(function (race) {
      var mins = (deadlineMs_(date, race.deadline) - now) / 60000;
      if (mins < 2 || mins > 9) return;          // 締切2〜9分前だけ。2分前を過ぎたら確定
      judgeRace_(date, race, unit);
    });
  } finally {
    lock.releaseLock();
  }
}

function judgeRace_(date, race, unit) {
  var judgedAt = Utilities.formatDate(new Date(), TZ, 'HH:mm:ss');
  var bi = fetchBoat_('beforeinfo', race.jcd, race.race, date);
  var w = parseWind(bi);
  var o3t, o2t, o3f, got = {};
  function need(kind) {                           // 成立したルールに必要なオッズだけ、1回ずつ取る
    if (got[kind]) return;
    got[kind] = true;
    if (kind === '3t') o3t = parseOdds3t(fetchBoat_('odds3t', race.jcd, race.race, date));
    if (kind === '2t') { var p = parseOdds2tf(fetchBoat_('odds2tf', race.jcd, race.race, date)); o2t = p ? p.t2 : null; }
    if (kind === '3f') o3f = parseOdds3f(fetchBoat_('odds3f', race.jcd, race.race, date));
  }
  race.rules.forEach(function (id) {
    var rule = RULES[id], status, bets = [], note = '';
    if (!rule) return;
    if (rule.wind && w.wind === null) {
      status = '保留'; note = '風速が取れず（次の回で再挑戦）';
    } else if (rule.wind && w.wind < WIND_MIN) {
      status = '不成立'; note = '風' + w.wind + 'm';
    } else {
      need(rule.bet.substr(0, 2));
      var b = buildBets(rule.bet, race, o3t, o2t, o3f);
      if (b === null) { status = '保留'; note = 'オッズが取れず（次の回で再挑戦）'; }
      else if (!b.length) { status = '見送り'; note = '該当オッズなし'; }
      else { status = '成立'; bets = b; }
    }
    upsertSnap_([date, race.jcd, String(race.race), id, rule.rank, judgedAt,
                 w.wind === null ? '' : String(w.wind), w.time, status, JSON.stringify(bets),
                 String(bets.length), String(bets.length * unit), race.deadline, race.venue, note]);
  });
}

function upsertSnap_(row) {
  var sh = book_().getSheetByName('snapshots');
  var last = sh.getLastRow();
  if (last > 1) {
    var keys = sh.getRange(2, 1, last - 1, 4).getValues();
    for (var i = keys.length - 1; i >= 0; i--) {
      if (String(keys[i][0]) === row[0] && String(keys[i][1]) === row[1] &&
          String(keys[i][2]) === row[2] && String(keys[i][3]) === row[3]) {
        sh.getRange(i + 2, 1, 1, row.length).setValues([row]);
        return;
      }
    }
  }
  sh.getRange(last + 1, 1, 1, row.length).setNumberFormat('@').setValues([row]);
}

// ==================================================================
// settle（毎朝6〜7時）
// ==================================================================
function settle() {
  var started = Date.now();
  var ss = book_(), snap = ss.getSheetByName('snapshots'), log = ss.getSheetByName('log');
  var today = today_();
  var done = {};
  if (log.getLastRow() > 1) {
    log.getRange(2, 1, log.getLastRow() - 1, 4).getValues().forEach(function (r) {
      done[r[0] + '|' + r[1] + '|' + r[2] + '|' + r[3]] = true;
    });
  }
  if (snap.getLastRow() < 2) return;
  var rows = snap.getRange(2, 1, snap.getLastRow() - 1, SNAP_HEAD.length).getValues();
  var results = {}, finals = {};
  for (var i = 0; i < rows.length; i++) {
    if (Date.now() - started > 4.5 * 60000) { Logger.log('時間切れ。残りは次回'); break; }
    var s = rows[i], date = String(s[0]), jcd = String(s[1]), race = String(s[2]), id = String(s[3]);
    if (String(s[8]) !== '成立' || date >= today || done[date + '|' + jcd + '|' + race + '|' + id]) continue;
    var rk = date + '|' + jcd + '|' + race;
    if (!(rk in results)) results[rk] = parseResult(fetchBoat_('raceresult', jcd, race, date));
    var res = results[rk];
    if (!res) continue;                          // 結果がまだ出ていない
    var rule = RULES[id], bets = JSON.parse(s[9] || '[]'), stake = Number(s[11]);
    var unit = bets.length ? Math.round(stake / bets.length) : 100;
    var st = settleBets(rule.bet, bets, res, unit);
    var kind = KIND_OF_BET[rule.bet.substr(0, 2)];
    var first = res.cancelled ? ['', ''] : (res[kind][0] || ['', '']);
    var hitOdds = st.hits.length ? bets.filter(function (b) { return b.combo === st.hits[0]; })[0].odds : '';
    var finalOdds = '';
    if (FINAL_ODDS_RULES[id] && !res.cancelled) {
      if (!(rk in finals)) finals[rk] = parseOdds3t(fetchBoat_('odds3t', jcd, race, date));
      if (finals[rk]) finalOdds = JSON.stringify(bets.map(function (b) { return [b.combo, b.odds, finals[rk][b.combo]]; }));
    }
    var row = [date, jcd, race, id, String(s[4]), String(bets.length), String(stake),
               res.cancelled ? '返還' : (st.hits.length ? '1' : '0'), String(st.pay),
               first[0], String(first[1]), hitOdds === null ? '' : String(hitOdds), finalOdds, String(s[13])];
    log.getRange(log.getLastRow() + 1, 1, 1, row.length).setNumberFormat('@').setValues([row]);
    done[date + '|' + jcd + '|' + race + '|' + id] = true;
  }
}

// ==================================================================
// doGet（ページ用JSON）
// ==================================================================
function doGet(e) {
  var p = (e && e.parameter) || {}, obj;
  try {
    obj = p.mode === 'summary' ? summary_() : day_(p.date || today_());
    obj.ok = true;
  } catch (err) {
    obj = { ok: false, error: String(err) };
  }
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function day_(date) {
  var sh = book_().getSheetByName('snapshots'), snaps = [];
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, SNAP_HEAD.length).getValues().forEach(function (r) {
      if (String(r[0]) !== date) return;
      var o = {};
      SNAP_HEAD.forEach(function (h, i) { o[h] = String(r[i]); });
      o.bets = JSON.parse(o.bets || '[]');
      snaps.push(o);
    });
  }
  return { date: date, now: Utilities.formatDate(new Date(), TZ, 'HH:mm'), targets: getTargets_(date), snapshots: snaps };
}

function summary_() {
  var sh = book_().getSheetByName('log'), by = {};
  function add(key, rule, rank, r) {
    var o = by[key] || (by[key] = { rule_id: rule, rank: rank, fy: key.split('|')[1] || '通算',
                                    races: 0, invest: 0, payout: 0, hits: 0 });
    o.races++; o.invest += Number(r[6]); o.payout += Number(r[8]); if (String(r[7]) === '1') o.hits++;
  }
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, LOG_HEAD.length).getValues().forEach(function (r) {
      var d = String(r[0]), y = Number(d.substr(0, 4)), m = Number(d.substr(5, 2));
      var fy = (m >= 10 ? y : y - 1) + '年度';     // 年度は10月始まり（冬ごとに区切る）
      add(r[3] + '|', r[3], String(r[4]), r);
      add(r[3] + '|' + fy, r[3], String(r[4]), r);
    });
  }
  var order = { '◎': 0, '△': 1, '×': 2 }, ids = Object.keys(RULES);
  var list = Object.keys(by).map(function (k) {
    var o = by[k];
    o.roi = o.invest ? Math.round(o.payout / o.invest * 1000) / 10 : null;
    return o;
  }).sort(function (a, b) {
    return (order[a.rank] - order[b.rank]) || (ids.indexOf(a.rule_id) - ids.indexOf(b.rule_id)) ||
           (a.fy === '通算' ? -1 : b.fy === '通算' ? 1 : a.fy < b.fy ? -1 : 1);
  });
  return { rules: RULES, summary: list };
}

// ==================================================================
// testParse（エディタで実行 → ログに ALL OK）
// ==================================================================
function testParse() {
  var fails = [];
  function check(name, got, want) {
    var ok = JSON.stringify(got) === JSON.stringify(want);
    Logger.log((ok ? 'OK  ' : 'NG  ') + name + (ok ? '' : '  got=' + JSON.stringify(got) + ' want=' + JSON.stringify(want)));
    if (!ok) fails.push(name);
  }
  function oddsHtml(s) {
    return s.split(' ').map(function (v) { return '<td class="oddsPoint">' + (v === '-' ? '欠場' : v) + '</td>'; }).join('');
  }
  // 2026-09-20 桐生2R（公式ページから抜き出した並び。tests/fixtures/ と同じ）
  var O3T = '23.2 57.0 37.4 38.7 140.6 1009 20.0 47.2 17.4 27.5 116.5 1168 54.7 86.5 41.4 41.1 91.8 1063 238.0 426.9 272.8 172.2 440.7 1557 17.5 88.4 67.6 62.3 182.3 1544 9.8 82.9 59.7 83.1 328.2 2165 28.1 176.5 116.4 111.7 288.7 1675 193.8 683.1 638.8 340.8 897.0 2432 19.6 79.5 22.2 29.9 144.6 2089 13.7 91.7 46.5 64.1 297.4 1830 34.0 156.2 36.9 57.3 149.8 1531 187.3 400.9 282.8 305.6 853.8 2192 91.9 126.7 64.9 42.8 94.4 1571 66.6 261.1 124.6 78.3 184.6 1629 78.1 177.7 59.2 58.4 135.8 2041 377.8 565.6 371.5 143.1 320.5 986.7 749.3 614.5 934.7 412.0 1096 1869 696.4 749.3 1644 454.2 1200 1930 590.0 638.8 1009 493.3 1160 1995 652.9 716.1 841.7 331.9 778.9 862.1';
  var O2TF = '9.5 17.3 7.6 9.9 33.1 131.7 6.0 37.0 20.4 19.3 81.4 497.5 7.6 28.3 9.6 13.5 49.7 344.4 22.3 66.8 21.5 19.6 38.6 235.6 95.2 319.8 131.7 77.2 213.2 373.1 9.5 3.1 12.9 3.6 12.2 4.5 15.4 53.8 26.9 17.9 28.6 149.5 79.1 70.8 79.1';
  var O3F = '6.5 6.2 20.0 51.1 3.0 10.5 9.9 25.3 35.1 112.5 9.1 19.8 12.2 34.7 96.9 78.1 66.9 108.1 87.8 41.3';
  // 2026-02-06 桐生5R（確定オッズ）
  var K0206 = '68.3 81.9 145.1 277.7 154.6 25.3 67.4 70.3 148.4 340.5 230.4 37.8 62.4 76.7 114.4 152.5 142.5 43.0 43.9 58.8 120.5 157.5 89.8 29.8 98.5 115.2 165.8 326.5 243.3 32.6 122.9 73.9 100.3 290.3 268.4 42.6 102.2 76.0 101.2 193.6 189.2 47.3 100.9 84.8 116.5 222.7 141.0 39.4 111.6 126.2 163.7 320.5 258.4 64.6 143.7 102.2 132.1 304.1 273.6 65.3 78.4 74.3 81.4 184.0 202.0 80.3 85.5 87.7 108.2 205.1 154.2 60.2 86.8 140.3 119.4 159.2 168.8 83.7 127.8 119.0 131.7 196.1 212.0 92.2 95.6 87.7 84.2 230.6 250.5 128.1 49.2 86.9 77.7 64.5 72.1 53.8 40.1 65.4 109.9 173.3 102.7 58.7 65.4 67.6 114.2 213.4 124.2 74.9 67.5 62.3 103.7 271.3 176.0 84.0 50.2 59.8 82.3 92.8 77.1 54.8';

  var o3t = parseOdds3t(oddsHtml(O3T)), tf = parseOdds2tf(oddsHtml(O2TF)), o3f = parseOdds3f(oddsHtml(O3F));
  check('3連単 5-2-3', o3t['5-2-3'], 328.2);
  check('2連単 5-2', tf.t2['5-2'], 81.4);
  check('2連複 2-5', tf.f2['2-5'], 53.8);
  check('3連複 2-3-5', o3f['2-3-5'], 25.3);
  check('119個では保留', parseOdds3t(oddsHtml(O3T.split(' ').slice(1).join(' '))), null);

  var res = parseResult('<td rowspan="2">3連単</td><td><span class="numberSet1_number is-type5">5</span>' +
    '<span class="numberSet1_number is-type2">2</span><span class="numberSet1_number is-type3">3</span></td>' +
    '<td><span class="is-payout1">&yen;32,820</span></td></tr><tr><td>&nbsp;</td></tbody>' +
    '<th>返還</th></tr></thead><tbody><tr><td></td></tr></tbody></table>');
  check('結果 3連単 5-2-3 32,820円', res['3連単'], [['5-2-3', 32820]]);
  check('結果なしは null', parseResult('<html>まだ</html>'), null);
  check('風速', parseWind('<span class="weather1_bodyUnitLabelTitle">風速</span>\n   <span class="weather1_bodyUnitLabelData">6m</span>').wind, 6);

  var k = buildBets('3t_X1Y_40_80_pop50', {}, parseOdds3t(oddsHtml(K0206)));
  check('KIR-A 2026-02-06 5R', k.map(function (b) { return b.combo + '(' + b.odds + ')'; }),
        ['2-1-4(70.3)', '2-1-5(76.7)', '2-1-6(58.8)', '6-1-4(43)']);
  check('KIR-A 的中 7,670円', settleBets('3t_X1Y_40_80_pop50', k,
        { '3連単': [['2-1-5', 7670]], henkan: [], cancelled: false }, 100), { pay: 7670, hits: ['2-1-5'] });
  check('中止は全額返還', settleBets('2t_X1', buildBets('2t_X1', {}, null, tf.t2), { cancelled: true }, 100).pay, 500);

  var race = { outer_top3: [6, 3, 2] };
  check('MAR-E BOX', buildBets('2t_outer_top3_box', race, null, tf.t2).map(function (b) { return b.combo; }),
        ['6-3', '6-2', '3-6', '3-2', '2-6', '2-3']);
  check('ASH-Q 1点', buildBets('3f_outer_top3', race, null, null, o3f)[0].combo, '2-3-6');
  check('W1-Q 10点', buildBets('3f_1XY_all', race, null, null, o3f).length, 10);
  check('WAK-C 20点', buildBets('3t_X1Y_all', race, o3t).length, 20);
  check('KIR-B', buildBets('2t_X1', race, null, tf.t2).map(function (b) { return b.combo; }), ['2-1', '3-1', '4-1', '5-1', '6-1']);

  Logger.log(fails.length ? 'FAILED: ' + fails.length + '件' : 'ALL OK');
}
