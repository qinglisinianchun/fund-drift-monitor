# -*- coding: utf-8 -*-
"""
生成监控看板 —— 自包含单文件 HTML，零外链
读取 数据/latest.json，输出 index.html
（文件名用 index.html 是为了 GitHub Pages：仓库根目录的 index.html 即站点首页）
支持时间范围切换：1个月 / 3个月 / 6个月 / 1年
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
# 范围按钮按「有效区间长度」自适应：只有积累足够数据才显示对应按钮
n_valid = len(dates)
RANGE_DEFS = [('1m', 22, '近1月'), ('3m', 62, '近3月'), ('6m', 125, '近半年'), ('1y', 250, '近1年')]
avail = [(k, n, lbl) for k, n, lbl in RANGE_DEFS if n_valid > n * 0.6]
# 至少保留两项；默认选中倒数第二项（或最大可用项）
if len(avail) < 2:
    avail = [(k, n, lbl) for k, n, lbl in RANGE_DEFS[:2]]
default_range = avail[-1][0] if len(avail) > 1 else avail[0][0]

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
}, ensure_ascii=False)

# 有效区间说明
acc_days = n_valid
acc_txt = f'当前已积累 <b>{acc_days}</b> 个交易日有效数据（{dates[0]} 起）'
if acc_days < 250:
    acc_txt += f'。随时间推进将自然补齐至一年，届时「近1年」等更长期按钮会自动出现。'

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>基金漂移监控看板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:#f5f6f8;color:#1f2329;padding:22px;line-height:1.6}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:21px;font-weight:600;margin-bottom:4px}}
.sub{{color:#8a9099;font-size:13px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}}
.card{{background:#fff;border-radius:10px;padding:14px 16px;border:1px solid #e8eaed}}
.card .k{{font-size:12px;color:#8a9099;margin-bottom:5px}}
.card .v{{font-size:20px;font-weight:600;letter-spacing:-.3px}}
.card .d{{font-size:12px;color:#8a9099;margin-top:3px}}
.panel{{background:#fff;border-radius:10px;padding:18px;border:1px solid #e8eaed;margin-bottom:16px}}
.panel h2{{font-size:15px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;
gap:10px;flex-wrap:wrap;justify-content:space-between}}
.panel h2 span.ttl{{display:flex;align-items:center;gap:8px}}
.badge{{font-size:12px;padding:2px 9px;border-radius:20px;font-weight:500}}
.g{{background:#e7f6ec;color:#0b7a37}} .r{{background:#fdeaea;color:#c1342f}}
.y{{background:#fff4e0;color:#a86a00}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:9px 10px;text-align:left;border-bottom:1px solid #f0f1f3}}
th{{color:#8a9099;font-weight:500;font-size:12.5px;background:#fafbfc}}
.good{{color:#0b7a37;font-weight:600}} .bad{{color:#c1342f;font-weight:600}}
.pos{{color:#c1342f}} .neg{{color:#0b7a37}}
.chart{{width:100%;height:auto;display:block}}
.tips{{font-size:13px;color:#5a6169;background:#f8f9fb;border-left:3px solid #d0d4d9;
padding:11px 14px;border-radius:0 7px 7px 0;margin-top:10px}}
.tips.warn{{background:#fff8ec;border-left-color:#e8a33d;color:#8a6210}}
.tips b{{color:#1f2329}}
.legend{{display:flex;gap:18px;font-size:12.5px;color:#5a6169;margin-top:10px;flex-wrap:wrap}}
.legend i{{display:inline-block;width:15px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}}
.seg{{display:inline-flex;background:#f0f1f3;border-radius:8px;padding:3px;gap:2px}}
.seg button{{border:0;background:transparent;font:inherit;font-size:12.5px;color:#5a6169;
padding:5px 13px;border-radius:6px;cursor:pointer;transition:.15s;white-space:nowrap}}
.seg button:hover{{color:#1f2329}}
.seg button.on{{background:#fff;color:#1f2329;font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.zoomhint{{font-size:12px;color:#a0a6ae;margin-top:8px}}
#chartNav{{cursor:crosshair}}
.tipbox{{position:fixed;display:none;pointer-events:none;background:rgba(29,33,40,.94);color:#fff;
font-size:12px;padding:9px 11px;border-radius:8px;line-height:1.75;z-index:99;white-space:nowrap;
box-shadow:0 6px 20px rgba(0,0,0,.28)}}
.tipbox .td{{color:#aeb6c2;font-size:11px;margin-bottom:4px}}
.tipbox .rr{{display:flex;align-items:center;gap:7px}}
.tipbox .rr i{{display:inline-block;width:9px;height:9px;border-radius:2px;flex:none}}
.tipbox .rr span{{margin-left:auto;padding-left:16px;font-weight:600}}
.tipbox .dd{{color:#c3c9d2;border-top:1px solid rgba(255,255,255,.16);margin-top:5px;padding-top:4px;
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
  <div class="legend"><span><i style="background:#3b6fd4"></i>080006（平替）</span>
  <span><i style="background:#e8912f"></i>270042（纳指100基准）</span>
  <span id="rangeInfo" style="color:#a0a6ae"></span></div>
</div>

<div class="panel">
  <h2>
    <span class="ttl">② 累计偏差走势（080006 相对纳指100 的超额）</span>
    <span class="seg" id="seg2">{btn_html}</span>
  </h2>
  <svg class="chart" id="chartDev" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg>
  <div class="legend"><span><i style="background:#2baac1"></i>累计超额偏差</span>
  <span style="color:#a0a6ae">纵轴自适应缩放</span></div>
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

function norm(arr) {{
  const b = arr[0];
  return arr.map(v => +(v / b * 100).toFixed(3));
}}

// 累计涨跌幅（%）：区间首日 = 0，之后为相对首日的涨跌百分比
function pct(arr) {{
  const b = arr[0];
  return arr.map(v => +((v / b - 1) * 100).toFixed(3));
}}

function drawLines(svg, series, colors, x0, x1, y0, y1, ymin, ymax, widthTop) {{
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
    ln.setAttribute('stroke', k === 4 ? '#e2e5e9' : '#eef0f2');
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
    t.setAttribute('font-size', '11'); t.setAttribute('fill', '#a0a6ae');
    t.textContent = fmt(v);
    svg.appendChild(t);
  }}
}}

function labelX(svg, first, last, y) {{
  const a = document.createElementNS(NS, 'text');
  a.setAttribute('x', 62); a.setAttribute('y', y);
  a.setAttribute('font-size', '11'); a.setAttribute('fill', '#a0a6ae');
  a.textContent = first; svg.appendChild(a);
  const b = document.createElementNS(NS, 'text');
  b.setAttribute('x', 985); b.setAttribute('y', y);
  b.setAttribute('text-anchor', 'end');
  b.setAttribute('font-size', '11'); b.setAttribute('fill', '#a0a6ae');
  b.textContent = last; svg.appendChild(b);
}}

// 取最近 n 天
function slice(arr, n) {{ return arr.slice(Math.max(0, arr.length - n)); }}

function render(rangeKey) {{
  const n = DATA.ranges[rangeKey];
  const dts = slice(DATA.dates, n);
  const av = pct(slice(DATA.A, n));
  const bv = pct(slice(DATA.B, n));
  const dvv = slice(DATA.dev.map(x => x[1]), n);

  // 图1（累计涨跌幅，首日 0%）
  const svg1 = document.getElementById('chartNav');
  const all = av.concat(bv, 0);
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.12, 0.3);
  const ymin1 = lo - pad, ymax1 = hi + pad;
  drawLines(svg1, [{{vals: av}}, {{vals: bv, dash: true}}],
            ['#3b6fd4', '#e8912f'], 62, 985, 18, 268, ymin1, ymax1);
  axisY(svg1, ymin1, ymax1, 18, 268, v => (v > 0 ? '+' : '') + v.toFixed(1) + '%');
  // 0% 基准线
  if (ymin1 < 0 && ymax1 > 0) {{
    const zy = 268 - (0 - ymin1) / (ymax1 - ymin1) * 250;
    const zl = document.createElementNS(NS, 'line');
    zl.setAttribute('x1', 62); zl.setAttribute('x2', 985);
    zl.setAttribute('y1', zy); zl.setAttribute('y2', zy);
    zl.setAttribute('stroke', '#c9ccd2'); zl.setAttribute('stroke-width', '1.5');
    svg1.insertBefore(zl, svg1.children[5] || null);
  }}
  labelX(svg1, dts[0], dts[dts.length - 1], 296);
  setupNavHover(dts, av, bv, ymin1, ymax1);

  // 图2（累计偏差，自适应缩放）
  const svg2 = document.getElementById('chartDev');
  const dl = Math.min(...dvv), dh = Math.max(...dvv);
  const dpad = Math.max((dh - dl) * 0.15, 0.15);
  const ylo = dl - dpad, yhi = dh + dpad;
  drawLines(svg2, [{{vals: dvv}}], ['#2baac1'], 62, 985, 18, 208, ylo, yhi);
  axisY(svg2, ylo, yhi, 18, 208, v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%');
  // 零轴
  if (ylo < 0 && yhi > 0) {{
    const zy = 208 - (0 - ylo) / (yhi - ylo) * 190;
    const zl = document.createElementNS(NS, 'line');
    zl.setAttribute('x1', 62); zl.setAttribute('x2', 985);
    zl.setAttribute('y1', zy); zl.setAttribute('y2', zy);
    zl.setAttribute('stroke', '#d8dbe0'); zl.setAttribute('stroke-width', '1.5');
    svg2.insertBefore(zl, svg2.children[5] || null);
  }}
  labelX(svg2, dts[0], dts[dts.length - 1], 238);

  document.getElementById('rangeInfo').textContent =
    '显示 ' + dts.length + ' 个交易日：' + dts[0] + ' ~ ' + dts[dts.length - 1];
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
  NAV = {{
    dts, av, bv, n,
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
    vl.setAttribute('stroke', '#b9bdc6'); vl.setAttribute('stroke-width', '1');
    vl.setAttribute('stroke-dasharray', '3 3');
    g.appendChild(vl);
    // 两条线上的圆点
    [['#3b6fd4', ya], ['#e8912f', yb]].forEach(([col, y]) => {{
      const dot = document.createElementNS(NS, 'circle');
      dot.setAttribute('cx', x); dot.setAttribute('cy', y);
      dot.setAttribute('r', 4); dot.setAttribute('fill', '#fff');
      dot.setAttribute('stroke', col); dot.setAttribute('stroke-width', '2');
      g.appendChild(dot);
    }});

    const diff = NAV.av[i] - NAV.bv[i];
    tip.innerHTML =
      '<div class="td">' + NAV.dts[i] + ' · 自首日起第 ' + (i + 1) + ' 个交易日</div>' +
      '<div class="rr"><i style="background:#3b6fd4"></i>080006<span>' + fmtPct(NAV.av[i]) + '</span></div>' +
      '<div class="rr"><i style="background:#e8912f"></i>270042<span>' + fmtPct(NAV.bv[i]) + '</span></div>' +
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

function bindSeg(id) {{
  document.getElementById(id).addEventListener('click', e => {{
    const b = e.target.closest('button');
    if (!b) return;
    document.querySelectorAll('#' + id + ' button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    render(b.dataset.r);
  }});
}}
bindSeg('seg'); bindSeg('seg2');
render(DATA.default || '3m');
bindNavHover();
</script>
</body></html>'''

open(OUT, 'w', encoding='utf-8').write(html)
print(f'✅ 看板已生成: {OUT}  ({len(html)} 字节)')
