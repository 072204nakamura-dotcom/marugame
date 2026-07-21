/* ============================================================
   会場切替ナビ – 全ページ共通
   ------------------------------------------------------------
   会場を増やすときは、下の VENUES に1行足すだけでOK。
   全ページのナビに自動で反映されます。

     name … ナビに出る表示名
     path … リポジトリのルートから見たフォルダ名
             （丸亀はルートそのものなので '' ＝空っぽ）

   並び順は 丸亀（ホーム）→ あとは公式の場コード順。
   ============================================================ */
var VENUES = [
  { name: '丸亀',   path: ''          },  // 15
  { name: '戸田',   path: 'toda'      },  // 02
  { name: '江戸川', path: 'edogawa'   },  // 03
  { name: '平和島', path: 'heiwajima' },  // 04
  { name: '津',     path: 'tsu'       },  // 09
  { name: '鳴門',   path: 'naruto'    },  // 14
  { name: '宮島',   path: 'miyajima'  },  // 17
  { name: '福岡',   path: 'fukuoka'   }   // 22
];

/* 各ページの <nav class="venues" data-venue="○○"></nav> を中身で埋める。
   data-venue には、そのページ自身の path を書いておく（丸亀は空でOK）。 */
(function () {
  var nav = document.querySelector('.venues');
  if (!nav) return;

  var here = nav.getAttribute('data-venue') || '';

  // 自分自身のsrc（'venues.js' か '../venues.js'）からルートまでの相対パスを求める
  var src  = document.currentScript ? document.currentScript.getAttribute('src') : 'venues.js';
  var base = src.replace(/venues\.js$/, '');

  nav.innerHTML = VENUES.map(function (v) {
    if (v.path === here) return '<span class="on">' + v.name + '</span>';
    return '<a href="' + base + (v.path ? v.path + '/' : '') + '">' + v.name + '</a>';
  }).join('');
})();
