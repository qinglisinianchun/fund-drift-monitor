# -*- coding: utf-8 -*-
"""
生成监控看板 —— 自包含单文件 HTML，零外链
读取 数据/latest.json，输出 index.html
（文件名用 index.html 是为了 GitHub Pages：仓库根目录的 index.html 即站点首页）
支持时间范围切换：1个月 / 3个月 / 6个月 / 1年（图①②各自独立切换）
跟随系统深浅色：设备切到夜间模式时自动套用深色配色（Apple HIG 深色系统色）
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, '数据')
OUT = os.path.join(BASE, 'index.html')

rep = json.load(open(os.path.join(DATA, 'latest.json'), encoding='utf-8'))
cfg_path = os.path.join(DATA, 'notify_config.json')
cfg = json.load(open(cfg_path, encoding='utf-8')) if os.path.exists(cfg_path) else {'channel': 'none'}

la, lb = rep['latest']['A'], rep['latest']['B']
dates = rep['series']['dates']
A = rep['series']['A']
B = rep['series']['B']
dev_series = rep.get('dev_series', {})
VALID_FROM = rep.get('valid_from', '2026-07-01')

th_map = {w['window']: w['threshold'] for w in rep['windows']}
CH = {'wecom_webhook': '企业微信群机器人', 'serverchan': 'Server酱',
      'pushplus': 'PushPlus', 'none': '未配置（仅本地记录）'}
channel_name = CH.get(cfg.get('channel', 'none'), cfg.get('channel'))

status = 'fail' if not rep['ok'] else ('alert' if (rep['triggers'] or rep['alerts']) else 'ok')
status_txt = {'ok': '正常', 'alert': '触发预警', 'fail': '巡检失败'}[status]
status_cls = {'ok': 'g', 'alert': 'r', 'fail': 'y'}[status]

wrows = ''.join(
    f"<tr><td>{w['window']} 日</td><td>±{w['threshold']}%</td>"
    f"<td class=\"{'neg' if w['current_dev'] < 0 else 'pos'}\">{w['current_dev']:+.3f}%</td>"
    f"<td>{w['hit_run']} / {w['need_days']}</td>"
    f"<td class=\"{'bad' if w['triggered'] else 'good'}\">{'🔴 触发' if w['triggered'] else '✅ 正常'}</td></tr>"
    for w in rep['windows'])

# 补跑信息块
def brief(ds, limit=8):
    if not ds:
        return '无'
    if len(ds) <= limit:
        return '、'.join(ds)
    return f'{ds[0]} ~ {ds[-1]}（共 {len(ds)} 个交易日）'


bf = rep.get('backfill') or []
newd = rep.get('new_dates') or []
if bf:
    backfill_html = f'<div class="tips warn">🔄 <b>本次补跑</b>：{brief(bf)}（上次未开机/未运行，已自动补齐）</div>'
elif newd:
    backfill_html = f'<div class="tips">📥 本次新拉取净值：{brief(newd)}</div>'
elif rep.get('first_run'):
    backfill_html = '<div class="tips">🆕 首次运行，已初始化历史净值缓存</div>'
else:
    backfill_html = '<div class="tips">ℹ️ 无新增交易日（净值尚未更新）</div>'

# 数据以 JSON 内嵌，供前端切换时间范围
#
# 范围按钮：四个区间**恒定显示**（2026-10-09 起改）。
#   原来按「有效数据长度」自适应隐藏 6m/1y（n_valid > n*0.6 才出现）：
#   但有效区间被 monitor.py 的 VALID_FROM = 2026-07-01 钉死，
#   短期内根本攒不到 125 / 250 个交易日，结果是用户想主动看更长区间却没有按钮可点。
#   现在一律显示；点更长区间时，前端会把起点夹到 VALID_FROM（见下面的 startIndex）。
n_valid = len(dates)
RANGE_DEFS = [('1m', 22, '近1月'), ('3m', 62, '近3月'), ('6m', 125, '近半年'), ('1y', 250, '近1年')]
avail = RANGE_DEFS
# 默认选中「能装满、且不越过有效起点」的最大区间 —— 与改动前保持一致（当前落在「近3月」）。
# 不直接取 avail[-1]，否则默认视图会被改成「近1年」，属改动外的行为变化。
fits = [k for k, n, _ in RANGE_DEFS if n_valid >= n]
default_range = fits[-1] if fits else RANGE_DEFS[0][0]

btn_html = ''.join(
    f'<button data-r="{k}"{" class=\"on\"" if k == default_range else ""}>{lbl}</button>'
    for k, n, lbl in avail)

payload = json.dumps({
    'dates': dates, 'A': A, 'B': B,
    'dev': rep['daily_dev']['series'],
    'devSeries': dev_series,
    'thresholds': th_map,
    'ranges': {k: n for k, n, _ in avail},
    'default': default_range,
    'validFrom': VALID_FROM,
    'nValid': n_valid,
}, ensure_ascii=False)

# 有效区间说明
acc_txt = (f'有效区间自 <b>{dates[0]}</b> 起，'
           f'两基金在 {VALID_FROM} 之前不具可比性。')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>基金漂移监控看板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}

/* ---------- 配色（浅色，与改动前一致） ---------- */
:root{{
color-scheme:light dark;
--bg-page:#f5f6f8;
--bg-card:#ffffff;
--bg-subtle:#fafbfc;
--bg-seg:#f0f1f3;
--bg-seg-on:#ffffff;
--bg-tips:#f8f9fb;
--bg-tips-warn:#fff8ec;
--line:#e8eaed;
--line-soft:#f0f1f3;
--line-tips:#d0d4d9;
--line-tips-warn:#e8a33d;
--txt:#1f2329;
--txt-2:#5a6169;
--txt-3:#8a9099;
--txt-4:#a0a6ae;
--up:#c1342f;
--down:#0b7a37;
--warn-txt:#8a6210;
--badge-g-bg:#e7f6ec; --badge-g-fg:#0b7a37;
--badge-r-bg:#fdeaea; --badge-r-fg:#c1342f;
--badge-y-bg:#fff4e0; --badge-y-fg:#a86a00;
--c-a:#3b6fd4; --c-b:#e8912f; --c-dev:#2baac1;
--grid:#eef0f2; --grid-strong:#e2e5e9;
--axis:#a0a6ae; --zero:#c9ccd2; --zero2:#d8dbe0;
--seg-shadow:0 1px 3px rgba(0,0,0,.08);
--tip-bg:rgba(29,33,40,.94); --tip-fg:#ffffff;
--tip-sub:#aeb6c2; --tip-dim:#c3c9d2; --tip-div:rgba(255,255,255,.16);
--tip-shadow:0 6px 20px rgba(0,0,0,.28);
}}

/* ---------- 夜间模式 ----------
   跟随系统：设备切到深色时自动生效（@media prefers-color-scheme）。
   取色参考 Apple HIG 深色系统色：
     systemBlue #0A84FF · systemOrange #FF9F0A · systemTeal #40C8E0
     systemRed #FF453A · systemGreen #30D158 · systemYellow #FFD60A
     systemGroupedBackground #000000 · secondarySystemGroupedBackground #1C1C1E
     tertiarySystemGroupedBackground #2C2C2E · separator #38383A
     label #FFFFFF · secondaryLabel rgba(235,235,245,.6) · quaternaryLabel rgba(235,235,245,.3)
   说明：只改深色这一套；浅色沿用改动前的配色，避免影响你已经看惯的样子。 */
@media (prefers-color-scheme: dark) {{
:root{{
--bg-page:#000000;
--bg-card:#1c1c1e;
--bg-subtle:#2c2c2e;
--bg-seg:#2c2c2e;
--bg-seg-on:#48484a;
--bg-tips:#1c1c1e;
--bg-tips-warn:#2a2314;
--line:#38383a;
--line-soft:#2c2c2e;
--line-tips:#48484a;
--line-tips-warn:#ff9f0a;
--txt:#ffffff;
--txt-2:rgba(235,235,245,.6);
--txt-3:rgba(235,235,245,.42);
--txt-4:rgba(235,235,245,.3);
--up:#ff453a;
--down:#30d158;
--warn-txt:#ffd60a;
--badge-g-bg:rgba(48,209,88,.18);  --badge-g-fg:#30d158;
--badge-r-bg:rgba(255,69,58,.18);  --badge-r-fg:#ff453a;
--badge-y-bg:rgba(255,214,10,.18); --badge-y-fg:#ffd60a;
--c-a:#0a84ff; --c-b:#ff9f0a; --c-dev:#40c8e0;
--grid:#2c2c2e; --grid-strong:#3a3a3c;
--axis:rgba(235,235,245,.4); --zero:#48484a; --zero2:#3a3a3c;
--seg-shadow:0 1px 3px rgba(0,0,0,.5);
--tip-bg:rgba(44,44,46,.96); --tip-fg:#ffffff;
--tip-sub:rgba(235,235,245,.6); --tip-dim:rgba(235,235,245,.45);
--tip-div:rgba(235,235,245,.16);
--tip-shadow:0 8px 26px rgba(0,0,0,.6);
}}
}}

body{{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg-page);color:var(--txt);padding:22px;line-height:1.6}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:21px;font-weight:600;margin-bottom:4px}}
.sub{{color:var(--txt-3);font-size:13px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}}
.card{{background:var(--bg-card);border-radius:10px;padding:14px 16px;border:1px solid var(--line)}}
.card .k{{font-size:12px;color:var(--txt-3);margin-bottom:5px}}
.card .v{{font-size:20px;font-weight:600;letter-spacing:-.3px}}
.card .d{{font-size:12px;color:var(--txt-3);margin-top:3px}}
.panel{{background:var(--bg-card);border-radius:10px;padding:18px;border:1px solid var(--line);margin-bottom:16px}}
.panel h2{{font-size:15px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;
gap:10px;flex-wrap:wrap;justify-content:space-between}}
.panel h2 span.ttl{{display:flex;align-items:center;gap:8px}}
.badge{{font-size:12px;padding:2px 9px;border-radius:20px;font-weight:500}}
.g{{background:var(--badge-g-bg);color:var(--badge-g-fg)}}
.r{{background:var(--badge-r-bg);color:var(--badge-r-fg)}}
.y{{background:var(--badge-y-bg);color:var(--badge-y-fg)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line-soft)}}
th{{color:var(--txt-3);font-weight:500;font-size:12.5px;background:var(--bg-subtle)}}
.good{{color:var(--down);font-weight:600}} .bad{{color:var(--up);font-weight:600}}
.pos{{color:var(--up)}} .neg{{color:var(--down)}}
.chart{{width:100%;height:auto;display:block}}
.tips{{font-size:13px;color:var(--txt-2);background:var(--bg-tips);border-left:3px solid var(--line-tips);
padding:11px 14px;border-radius:0 7px 7px 0;margin-top:10px}}
.tips.warn{{background:var(--bg-tips-warn);border-left-color:var(--line-tips-warn);color:var(--warn-txt)}}
.tips b{{color:var(--txt)}}
.legend{{display:flex;gap:18px;font-size:12.5px;color:var(--txt-2);margin-top:10px;flex-wrap:wrap}}
.legend i{{display:inline-block;width:15px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}}
.muted{{color:var(--txt-4)}}
.sw-a{{background:var(--c-a)}} .sw-b{{background:var(--c-b)}} .sw-dev{{background:var(--c-dev)}}
.seg{{display:inline-flex;background:var(--bg-seg);border-radius:8px;padding:3px;gap:2px}}
.seg button{{border:0;background:transparent;font:inherit;font-size:12.5px;color:var(--txt-2);
padding:5px 13px;border-radius:6px;cursor:pointer;transition:.15s;white-space:nowrap}}
.seg button:hover{{color:var(--txt)}}
.seg button.on{{background:var(--bg-seg-on);color:var(--txt);font-weight:600;box-shadow:var(--seg-shadow)}}
.zoomhint{{font-size:12px;color:var(--txt-4);margin-top:8px}}
#chartNav{{cursor:crosshair}}
.tipbox{{position:fixed;display:none;pointer-events:none;background:var(--tip-bg);color:var(--tip-fg);
font-size:12px;padding:9px 11px;border-radius:8px;line-height:1.75;z-index:99;white-space:nowrap;
box-shadow:var(--tip-shadow)}}
.tipbox .td{{color:var(--tip-sub);font-size:11px;margin-bottom:4px}}
.tipbox .rr{{display:flex;align-items:center;gap:7px}}
.tipbox .rr i{{display:inline-block;width:9px;height:9px;border-radius:2px;flex:none}}
.tipbox .rr span{{margin-left:auto;padding-left:16px;font-weight:600}}
.tipbox .dd{{color:var(--tip-dim);border-top:1px solid var(--tip-div);margin-top:5px;padding-top:4px;
display:flex;justify-content:space-between;gap:18px;font-size:11.5px}}
</style>
</head>
<body><div id="tip" class="tipbox"></div>
<div class="wrap">
<h1>基金漂移监控看板 <span class="badge {status_cls}">{status_txt}</span></h1>
<div class="sub">巡检时间 {rep['run_at']} · 数据区间 {rep['range']} · 推送通道：{channel_name}</div>

<div class="grid">
  <div class="card"><div class="k">080006 长盛环球行业混合A</div>
    <div class="v">{la['nav']}</div>
    <div class="d {'pos' if (la['chg'] or 0) > 0 else 'neg'}">{la['chg']:+.2f}% · {la['d']}</div>
    <div class="d">申购状态：{la['sg']}</div></div>
  <div class="card"><div class="k">270042 广发纳指100ETF联接A</div>
    <div class="v">{lb['nav']}</div>
    <div class="d {'pos' if (lb['chg'] or 0) > 0 else 'neg'}">{lb['chg']:+.2f}% · {lb['d']}</div>
    <div class="d">申购状态：{lb['sg']}</div></div>
  <div class="card"><div class="k">最新交易日偏差</div>
    <div class="v {'pos' if rep['daily_dev']['current'] > 0 else 'neg'}">{rep['daily_dev']['current']:+.3f}%</div>
    <div class="d">{la['d']}</div></div>
  <div class="card"><div class="k">最大偏离窗口</div>
    <div class="v">{max(rep['windows'], key=lambda w: abs(w['current_dev']))['window']} 日</div>
    <div class="d">偏差 {max(rep['windows'], key=lambda w: abs(w['current_dev']))['current_dev']:+.3f}%</div></div>
</div>

{backfill_html}

<div class="panel">
  <h2>
    <span class="ttl">① 净值走势对比（累计涨跌幅，区间起点 = 0%）</span>
    <span class="seg" id="seg">{btn_html}</span>
  </h2>
  <svg class="chart" id="chartNav" viewBox="0 0 1000 320" preserveAspectRatio="none"></svg>
  <div class="legend"><span><i class="sw-a"></i>080006（平替）</span>
  <span><i class="sw-b"></i>270042（纳指100基准）</span>
  <span id="rangeInfo" class="muted"></span></div>
  <div class="tips">{acc_txt}</div>
</div>

<div class="panel">
  <h2>
    <span class="ttl">② 累计偏差走势（080006 相对纳指100 的超额）</span>
    <span class="seg" id="seg2">{btn_html}</span>
  </h2>
  <svg class="chart" id="chartDev" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg>
  <div class="legend"><span><i class="sw-dev"></i>累计超额偏差</span>
  <span class="muted">纵轴自适应缩放</span></div>
  <div class="tips">这条线就是「漂移计」——越平越好。出现单边持续抬升或下滑需警惕。</div>
</div>

<div class="panel">
  <h2>③ 滚动偏差校验（多窗口 · 连续 2 天确认）</h2>
  <table>
    <tr><th>窗口</th><th>触发阈值</th><th>最新偏差</th><th>连续超限</th><th>状态</th></tr>
    {wrows}
  </table>
  <div class="tips">阈值以 <b>2026-07 起「真对齐期」</b>校准（3σ 原则）。该区间历史最大偏差仅 0.8%，
  故对齐期内零误报；一旦偏差走到 2026-06 的水平（std 0.84%）即会稳定命中。</div>
</div>

<div class="panel">
  <h2>④ 监控机制说明</h2>
  <table>
    <tr><th>项目</th><th>内容</th></tr>
    <tr><td>被监控</td><td>080006 长盛环球行业混合(QDII)A</td></tr>
    <tr><td>基准</td><td>270042 广发纳斯达克100ETF联接(QDII)人民币A</td></tr>
    <tr><td>核心指标</td><td>两基金 3/5/7/10 日滚动收益率之差</td></tr>
    <tr><td>触发条件</td><td>任一窗口偏差超阈值 <b>且连续 2 个交易日</b>成立</td></tr>
    <tr><td>红灯线</td><td>3日 2.0% / 5日 2.2% / 7日 2.5% / 10日 3.0%（单次即报）</td></tr>
    <tr><td>巡检频率</td><td>每日凌晨 3:00 云端自动巡检；每周日 3:00 另推送一周周报</td></tr>
    <tr><td>提醒方式</td><td>{channel_name}</td></tr>
    <tr><td>数据源</td><td>东方财富历史净值</td></tr>
  </table>
</div>

<div class="sub" style="text-align:center;margin-top:8px">
  生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 数据仅供参考，不构成投资建议
</div>
</div>

<script>
const DATA = {payload};
const NS = 'http://www.w3.org/2000/svg';

// ---------- 图表配色：从 CSS 变量取 ----------
// 深浅两套配色只在 <style> 里定义一次，线条/网格/坐标轴颜色跟着系统主题走。
let T = {{}};
function theme() {{
  const cs = getComputedStyle(document.documentElement);
  const v = n => cs.getPropertyValue(n).trim();
  return {{
    a: v('--c-a'), b: v('--c-b'), dev: v('--c-dev'),
    grid: v('--grid'), gridStrong: v('--grid-strong'),
    axis: v('--axis'), zero: v('--zero'), zero2: v('--zero2'),
    card: v('--bg-card')
  }};
}}

// 累计涨跌幅（%）：区间首日 = 0，之后为相对首日的涨跌百分比
function pct(arr) {{
  const b = arr[0];
  return arr.map(v => +((v / b - 1) * 100).toFixed(3));
}}

function drawLines(svg, series, colors, x0, x1, y0, y1, ymin, ymax) {{
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const n = series[0].vals.length;
  const span = (ymax - ymin) || 1;
  const px = i => x0 + (n <= 1 ? 0 : i * (x1 - x0) / (n - 1));
  const py = v => y1 - (v - ymin) / span * (y1 - y0);
  // 网格
  for (let k = 0; k <= 4; k++) {{
    const y = y0 + k * (y1 - y0) / 4;
    const ln = document.createElementNS(NS, 'line');
    ln.setAttribute('x1', x0); ln.setAttribute('x2', x1);
    ln.setAttribute('y1', y); ln.setAttribute('y2', y);
    ln.setAttribute('stroke', k === 4 ? T.gridStrong : T.grid);
    ln.setAttribute('stroke-width', '1');
    svg.appendChild(ln);
  }}
  series.forEach((s, si) => {{
    let d = '';
    s.vals.forEach((v, i) => {{ d += (i ? ' L ' : 'M ') + px(i).toFixed(1) + ',' + py(v).toFixed(1); }});
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', colors[si]);
    p.setAttribute('stroke-width', '2');
    p.setAttribute('stroke-linejoin', 'round');
    if (s.dash) p.setAttribute('stroke-dasharray', '5 3');
    svg.appendChild(p);
  }});
  return {{px, py}};
}}

function axisY(svg, ymin, ymax, y0, y1, fmt, x) {{
  for (let k = 0; k <= 4; k++) {{
    const y = y0 + k * (y1 - y0) / 4;
    const v = ymax - k * (ymax - ymin) / 4;
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x || 52); t.setAttribute('y', y + 4);
    t.setAttribute('text-anchor', 'end');
    t.setAttribute('font-size', '11'); t.setAttribute('fill', T.axis);
    t.textContent = fmt(v);
    svg.appendChild(t);
  }}
}}

function labelX(svg, first, last, y) {{
  const a = document.createElementNS(NS, 'text');
  a.setAttribute('x', 62); a.setAttribute('y', y);
  a.setAttribute('font-size', '11'); a.setAttribute('fill', T.axis);
  a.textContent = first; svg.appendChild(a);
  const b = document.createElementNS(NS, 'text');
  b.setAttribute('x', 985); b.setAttribute('y', y);
  b.setAttribute('text-anchor', 'end');
  b.setAttribute('font-size', '11'); b.setAttribute('fill', T.axis);
  b.textContent = last; svg.appendChild(b);
}}

// 取最近 n 天，但**不得越过有效起点 VALID_FROM**。
// 两基金在 2026-07-01 之前不具可比性，因此点「近半年 / 近一年」时，
// 起点一律夹到 VALID_FROM —— 起始日期就是 2026-07-01。
function startIndex(n) {{
  const total = DATA.dates.length;
  let s = Math.max(0, total - n);
  const vf = DATA.validFrom;
  if (vf) {{
    let i = 0;
    while (i < total && DATA.dates[i] < vf) i++;
    s = Math.max(s, i);
  }}
  return s;
}}

// 累计偏差按**日期**取值：它比 dates 少一天（首日无偏差），按索引切会错位
const DEV_MAP = new Map((DATA.dev || []).map(p => [p[0], p[1]]));

// 两个面板各存各的选中区间，互不相干
const state = {{ nav: DATA.default || '3m', dev: DATA.default || '3m' }};

// ---------- 图①：净值走势对比 ----------
function renderNav() {{
  T = theme();
  const n = DATA.ranges[state.nav];
  const s = startIndex(n);
  const dts = DATA.dates.slice(s);
  const av = pct(DATA.A.slice(s));
  const bv = pct(DATA.B.slice(s));

  const svg1 = document.getElementById('chartNav');
  const all = av.concat(bv, 0);
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.12, 0.3);
  const ymin1 = lo - pad, ymax1 = hi + pad;
  drawLines(svg1, [{{vals: av}}, {{vals: bv, dash: true}}],
            [T.a, T.b], 62, 985, 18, 268, ymin1, ymax1);
  axisY(svg1, ymin1, ymax1, 18, 268, v => (v > 0 ? '+' : '') + v.toFixed(1) + '%');
  // 0% 基准线
  if (ymin1 < 0 && ymax1 > 0) {{
    const zy = 268 - (0 - ymin1) / (ymax1 - ymin1) * 250;
    const zl = document.createElementNS(NS, 'line');
    zl.setAttribute('x1', 62); zl.setAttribute('x2', 985);
    zl.setAttribute('y1', zy); zl.setAttribute('y2', zy);
    zl.setAttribute('stroke', T.zero); zl.setAttribute('stroke-width', '1.5');
    svg1.insertBefore(zl, svg1.children[5] || null);
  }}
  labelX(svg1, dts[0], dts[dts.length - 1], 296);
  setupNavHover(dts, av, bv, ymin1, ymax1);

  document.getElementById('rangeInfo').textContent =
    '显示 ' + dts.length + ' 个交易日：' + dts[0] + ' ~ ' + dts[dts.length - 1];
}}

// ---------- 图②：累计偏差走势 ----------
function renderDev() {{
  T = theme();
  const n = DATA.ranges[state.dev];
  const s = startIndex(n);
  const dts = DATA.dates.slice(s);
  const dvv = dts.map(d => DEV_MAP.get(d)).filter(v => v !== undefined);
  if (!dvv.length) dvv.push(0);

  const svg2 = document.getElementById('chartDev');
  const dl = Math.min(...dvv), dh = Math.max(...dvv);
  const dpad = Math.max((dh - dl) * 0.15, 0.15);
  const ylo = dl - dpad, yhi = dh + dpad;
  drawLines(svg2, [{{vals: dvv}}], [T.dev], 62, 985, 18, 208, ylo, yhi);
  axisY(svg2, ylo, yhi, 18, 208, v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%');
  // 零轴
  if (ylo < 0 && yhi > 0) {{
    const zy = 208 - (0 - ylo) / (yhi - ylo) * 190;
    const zl = document.createElementNS(NS, 'line');
    zl.setAttribute('x1', 62); zl.setAttribute('x2', 985);
    zl.setAttribute('y1', zy); zl.setAttribute('y2', zy);
    zl.setAttribute('stroke', T.zero2); zl.setAttribute('stroke-width', '1.5');
    svg2.insertBefore(zl, svg2.children[5] || null);
  }}
  labelX(svg2, dts[0], dts[dts.length - 1], 238);
}}

// ---------- 图1 鼠标悬停浮窗 ----------
let NAV = null;
function setupNavHover(dts, av, bv, ymin, ymax) {{
  const svg = document.getElementById('chartNav');
  const old = document.getElementById('navHover');
  if (old) old.remove();
  const g = document.createElementNS(NS, 'g');
  g.id = 'navHover';
  g.setAttribute('display', 'none');
  svg.appendChild(g);
  const n = dts.length;
  // 颜色在重建时固化，保证悬停层与已画出的两条线同色
  NAV = {{
    dts, av, bv, n,
    colA: T.a, colB: T.b, axis: T.axis, card: T.card,
    px: i => 62 + (n <= 1 ? 0 : i * (985 - 62) / (n - 1)),
    py: v => 268 - (v - ymin) / ((ymax - ymin) || 1) * (268 - 18)
  }};
}}

function bindNavHover() {{
  const svg = document.getElementById('chartNav');
  const tip = document.getElementById('tip');
  const fmtPct = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';

  svg.addEventListener('mousemove', e => {{
    if (!NAV) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const c = pt.matrixTransform(svg.getScreenCTM().inverse());
    let i = Math.round((c.x - 62) / (985 - 62) * (NAV.n - 1));
    i = Math.max(0, Math.min(NAV.n - 1, i));
    const x = NAV.px(i), ya = NAV.py(NAV.av[i]), yb = NAV.py(NAV.bv[i]);

    const g = document.getElementById('navHover');
    g.setAttribute('display', '');
    while (g.firstChild) g.removeChild(g.firstChild);
    // 竖向虚线
    const vl = document.createElementNS(NS, 'line');
    vl.setAttribute('x1', x); vl.setAttribute('x2', x);
    vl.setAttribute('y1', 18); vl.setAttribute('y2', 268);
    vl.setAttribute('stroke', NAV.axis); vl.setAttribute('stroke-width', '1');
    vl.setAttribute('stroke-dasharray', '3 3');
    g.appendChild(vl);
    // 两条线上的圆点
    [[NAV.colA, ya], [NAV.colB, yb]].forEach(([col, y]) => {{
      const dot = document.createElementNS(NS, 'circle');
      dot.setAttribute('cx', x); dot.setAttribute('cy', y);
      dot.setAttribute('r', 4); dot.setAttribute('fill', NAV.card);
      dot.setAttribute('stroke', col); dot.setAttribute('stroke-width', '2');
      g.appendChild(dot);
    }});

    const diff = NAV.av[i] - NAV.bv[i];
    tip.innerHTML =
      '<div class="td">' + NAV.dts[i] + ' · 自首日起第 ' + (i + 1) + ' 个交易日</div>' +
      '<div class="rr"><i class="sw-a"></i>080006<span>' + fmtPct(NAV.av[i]) + '</span></div>' +
      '<div class="rr"><i class="sw-b"></i>270042<span>' + fmtPct(NAV.bv[i]) + '</span></div>' +
      '<div class="dd"><span>累计偏差</span><span>' + fmtPct(diff) + '</span></div>';
    tip.style.display = 'block';

    const w = tip.offsetWidth, h = tip.offsetHeight;
    let left = e.clientX + 14, top = e.clientY + 14;
    if (left + w > window.innerWidth - 10) left = e.clientX - w - 14;
    if (top + h > window.innerHeight - 10) top = e.clientY - h - 14;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }});

  svg.addEventListener('mouseleave', () => {{
    const g = document.getElementById('navHover');
    if (g) g.setAttribute('display', 'none');
    tip.style.display = 'none';
  }});
}}

// 每个按钮组各管各的那张图 —— 点②不会再带着①一起变
function bindSeg(id, key, draw) {{
  document.getElementById(id).addEventListener('click', e => {{
    const b = e.target.closest('button');
    if (!b) return;
    document.querySelectorAll('#' + id + ' button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    state[key] = b.dataset.r;
    draw();
  }});
}}
bindSeg('seg', 'nav', renderNav);
bindSeg('seg2', 'dev', renderDev);
renderNav();
renderDev();
bindNavHover();

// 系统深浅色切换时重绘（线条颜色取自 CSS 变量，不重绘会留在旧配色）
const MQ = window.matchMedia('(prefers-color-scheme: dark)');
const onScheme = () => {{ renderNav(); renderDev(); }};
if (MQ.addEventListener) MQ.addEventListener('change', onScheme);
else if (MQ.addListener) MQ.addListener(onScheme);
</script>
</body></html>'''

open(OUT, 'w', encoding='utf-8').write(html)
print(f'✅ 看板已生成: {OUT}  ({len(html)} 字节)')
