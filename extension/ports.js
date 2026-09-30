/* 端口与身份常量 —— 唯一来源，只被 background.js 用 importScripts 加载。
 *
 * ⚠️ DP_PREFERRED_PORTS 必须与 D:\waimao\dp\客户开发工具.py 里的 PREFERRED_PORTS 保持一致。
 *    那个工具启动时会实测挑一个能 bind 的端口（Windows 把成片 TCP 端口保留给 Hyper-V/WinNAT，
 *    保留段每次开机漂移，所以端口不能写死），并把真实端口通过 /api/ping 报出来。
 *    扩展就是拿着这份候选表逐个试 /api/ping。
 *    改动任一边都要同步另一边 —— 两边都留了指向对方的注释。
 *
 * 这里用 var 而不用 const，是为了兼容两种加载方式：
 *   · background.js —— importScripts('ports.js')，经典 Service Worker，与主脚本共享全局作用域；
 *   · 普通扩展页面 —— <script src="ports.js">，会挂到 window 上。
 * var 在两种环境里都会落到对应的全局对象上，const/let 在页面里不会挂到 window，容易踩坑。
 */
var DP_PREFERRED_PORTS = [5000, 8000, 8080, 8765, 9000, 7000, 6500, 5800, 5555];

/* 用 /api/ping 的 app 字段做身份校验：本机可能跑着别的服务、也可能撞上同名路径，
   只有 ok==true && app=='waimao-dp' 才认，避免误连。 */
var DP_APP_ID = 'waimao-dp';

/* 单条 ping 的超时。本机「端口没人监听」是立刻 RST，不会真等满这个时间；
   它只兜住「端口被占着但不应答」这种少见情况。9 个候选并行发，整体也就百毫秒级。 */
var DP_PING_TIMEOUT_MS = 700;

/* 采集请求的超时：升级抓取要开 Chromium 完整跑一遍，单条最慢十几秒，给足余量。 */
var DP_COLLECT_TIMEOUT_MS = 60000;
