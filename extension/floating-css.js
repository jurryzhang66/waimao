/* 悬浮按钮的样式 —— 以 **JS 字符串** 形式提供，不是 .css 文件。
 *
 * 为什么不写成 floating.css 由 manifest 的 content_scripts.css 注入（这是最初的设想）：
 *   ① manifest 注入的样式表落在**页面文档**里，而我们的按钮在 **Shadow DOM** 内部；
 *      文档样式不跨越 shadow 边界，所以 floating.css 根本管不到按钮 → 设想不成立。
 *   ② 那就在 shadow 里塞 <style> 或 <link rel=stylesheet>？不行 —— 内容脚本 JS 虽然不受
 *      页面 CSP 约束，但它**插进页面 DOM 的元素**受页面 CSP 管：严格 style-src 的站点
 *      （GitHub、各大银行、很多 B2B 站）会把 <style> 和外部样式表直接拦掉，按钮就裸奔了。
 *   ③ 写 style="..." 内联属性同理会被 style-src 拦（且 setAttribute('style') 也在拦截范围内）。
 *
 * 所以走 **构造式样式表（CSSStyleSheet + adoptedStyleSheets）**：
 *   · 它是纯 CSSOM 操作，不属于 CSP 的管辖范围（规范里 style-src 只管 <style>/<link>/
 *     style 属性，不管 CSSOM API），任何站点都拦不住；
 *   · 挂到 shadowRoot.adoptedStyleSheets 上，天然只作用于我们的 Shadow DOM，与页面样式互不污染。
 *
 * 代价是 CSS 变成了 JS 字符串（本文件），不再是高亮的 .css 文件 —— 换来的是「永不裸奔」。
 * 改样式直接改下面的字符串即可；别加反引号，也别用 ${...}，会被模板字符串吃掉。
 *
 * content_scripts.js 里本文件必须排在 content.js **前面**：两者共享同一个 isolated world
 * 的全局作用域，content.js 要同步读到 DP_FLOATING_CSS（这样按钮不会先裸奔再补样式）。
 */
var DP_FLOATING_CSS = String.raw`
:host {
  /* all:initial 把宿主元素从页面样式继承里摘出来（页面若写了 * { ... } 也污染不到我们）。
     再把宿主本身压成 0×0 的块：真正的按钮在 .dp-wrap 里用 position:fixed 脱离文档流，
     所以宿主不会占位、也不会挡住页面上任何元素的点击。 */
  all: initial;
  display: block;
  width: 0;
  height: 0;
}

.dp-wrap {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2147483600;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.4;
  color: #202124;
  -webkit-font-smoothing: antialiased;
}

.dp-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ---------- 主按钮 ---------- */
.dp-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 44px;
  padding: 0 18px 0 14px;
  border: 0;
  border-radius: 22px;
  background: #1a73e8;
  color: #ffffff;
  font: inherit;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  box-shadow: 0 6px 18px rgba(26, 115, 232, .34), 0 1px 3px rgba(0, 0, 0, .18);
  transition: background .15s, transform .15s, box-shadow .15s;
}
.dp-btn:hover  { background: #1765cc; transform: translateY(-1px);
                 box-shadow: 0 8px 22px rgba(26, 115, 232, .42); }
.dp-btn:active { transform: translateY(0); }
.dp-btn:focus-visible { outline: 3px solid rgba(26, 115, 232, .35); outline-offset: 2px; }
.dp-btn[disabled] { cursor: default; }

.dp-btn.is-busy { background: #5f6368; }
.dp-btn.is-ok   { background: #188038; box-shadow: 0 6px 18px rgba(24, 128, 56, .34); }
.dp-btn.is-dup  { background: #5f6368; box-shadow: 0 6px 18px rgba(95, 99, 104, .30); }
.dp-btn.is-err  { background: #d93025; box-shadow: 0 6px 18px rgba(217, 48, 37, .34); }

.dp-ico { display: inline-flex; width: 18px; height: 18px; }
.dp-ico svg { display: block; width: 18px; height: 18px; }

/* 转圈：用纯 CSS 画，省一次图标请求 */
.dp-spin {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, .35);
  border-top-color: #ffffff;
  animation: dp-rot .7s linear infinite;
}
@keyframes dp-rot { to { transform: rotate(360deg); } }

/* ---------- 「在这个网站上隐藏」 ---------- */
.dp-hide {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid #dadce0;
  border-radius: 50%;
  background: #ffffff;
  color: #5f6368;
  font: inherit;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s, background .15s;
}
.dp-wrap:hover .dp-hide { opacity: 1; }
.dp-hide:focus-visible { opacity: 1; outline: 2px solid #1a73e8; outline-offset: 1px; }
.dp-hide:hover { background: #f1f3f4; color: #202124; }

/* ---------- 就地小提示 ---------- */
.dp-toast {
  display: none;
  max-width: 340px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #202124;
  color: #ffffff;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-line;
  word-break: break-word;
  box-shadow: 0 8px 24px rgba(0, 0, 0, .28);
}
.dp-toast.show { display: block; }
.dp-toast.ok   { background: #0d652d; }
.dp-toast.dup  { background: #3c4043; }
.dp-toast.err  { background: #a50e0e; }
`;
