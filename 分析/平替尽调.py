# -*- coding: utf-8 -*-
"""
平替尽调 —— 评估某只基金能否作为纳指100 的平替（同时建立净值缓存）

用法: python 平替尽调.py 016701
"""
import urllib.request, json, re, os, sys, time, math

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, '数据')
os.makedirs(DATA, exist_ok=True)

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
KEEP = 260


def http_get(url, referer=None, timeout=25, retries=3):
    h = dict(UA)
    if referer:
        h['Referer'] = referer
    last = None
    for i in range(retries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=h), timeout=timeout
            ).read().decode('utf-8', 'replace')
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2)
    raise RuntimeError(f'请求失败 {url}: {last}')


def fetch_nav(code, max_pages=20):
    rows = []
    for p in range(1, max_pages + 1):
        url = ('https://api.fund.eastmoney.com/f10/lsjz'
               f'?fundCode={code}&pageIndex={p}&pageSize=20')
        raw = http_get(url, referer=f'https://fundf10.eastmoney.com/jjjz_{code}.html')
        d = json.loads(raw)
        lst = (d.get('Data') or {}).get('LSJZList') or []
        if not lst:
            break
        for r in lst:
            rows.append({
                'd': r['FSRQ'],
                'nav': float(r['DWJZ']) if r.get('DWJZ') else None,
                'cum': float(r['LJJZ']) if r.get('LJJZ') else None,
                'chg': float(r['JZZZL']) if r.get('JZZZL') not in (None, '') else None,
                'sg': r.get('SGZT', ''),
                'sh': r.get('SHZT', ''),
            })
        time.sleep(0.55)
    seen, out = set(), []
    for r in rows:
        if r['d'] in seen:
            continue
        seen.add(r['d'])
        out.append(r)
    out.sort(key=lambda x: x['d'])
    return out


def load_or_fetch(code, force=False):
    """有缓存就用缓存合并最新，否则全量拉"""
    path = os.path.join(DATA, f'nav_{code}.json')
    old = []
    if os.path.exists(path) and not force:
        try:
            old = json.load(open(path, encoding='utf-8'))
        except Exception:
            old = []
    fresh = fetch_nav(code)
    m = {r['d']: r for r in old}
    for r in fresh:
        m[r['d']] = r
    merged = sorted(m.values(), key=lambda x: x['d'])[-KEEP:]
    json.dump(merged, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return merged


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float('nan')
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy) if vx and vy else float('nan')


def std(v):
    n = len(v)
    if n < 2:
        return 0.0
    m = sum(v) / n
    return math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))


def cum_ret(m, d0, d1):
    a, b = m.get(d0), m.get(d1)
    if not a or not b or not a['cum'] or not b['cum']:
        return None
    return (b['cum'] / a['cum'] - 1) * 100


def analyze(label, tmap, bmap, since=None):
    common = sorted(set(tmap) & set(bmap))
    if since:
        common = [d for d in common if d >= since]
    if len(common) < 15:
        print(f'\n【{label}】可比交易日不足（{len(common)} 天）')
        return None

    rt, rb = {}, {}
    for i in range(1, len(common)):
        d0, d1 = common[i - 1], common[i]
        a0, a1 = tmap.get(d0), tmap.get(d1)
        b0, b1 = bmap.get(d0), bmap.get(d1)
        if a0 and a1 and b0 and b1 and a0['cum'] and a1['cum'] and b0['cum'] and b1['cum']:
            rt[d1] = (a1['cum'] / a0['cum'] - 1) * 100
            rb[d1] = (b1['cum'] / b0['cum'] - 1) * 100
    days = [d for d in common if d in rt and d in rb]
    ta = [rt[d] for d in days]
    ba = [rb[d] for d in days]
    dev = [x - y for x, y in zip(ta, ba)]

    corr = pearson(ta, ba)
    sdev = std(dev)
    te = sdev * math.sqrt(252)

    ct = cum_ret(tmap, days[0], days[-1])
    cb = cum_ret(bmap, days[0], days[-1])

    print(f'\n{"="*68}')
    print(f'【{label}】  {days[0]} ~ {days[-1]}  ({len(days)} 个日收益样本)')
    print(f'{"="*68}')
    print(f'  日收益相关系数      {corr:.4f}      ← 越接近1越像纳指')
    print(f'  日偏差标准差        {sdev:.4f}%      ← 越小越稳')
    print(f'  年化跟踪误差        {te:.2f}%')
    if ct is not None and cb is not None:
        print(f'  本基金累计收益      {ct:+.2f}%')
        print(f'  270042 累计收益     {cb:+.2f}%')
        print(f'  区间累计偏差        {ct-cb:+.2f}%      ← 越小越贴合')
    mx = max(dev) if dev else 0
    mn = min(dev) if dev else 0
    print(f'  单日偏差极值        {mn:+.2f}% ~ {mx:+.2f}%')

    # 逐月
    print('\n  ── 逐月相关性（看是否一直对齐）──')
    print(f'  {"月份":<9}{"相关系数":>10}{"日偏差std":>11}{"月收益差":>11}{"样本":>6}')
    for mo in sorted({d[:7] for d in days}):
        idx = [i for i, d in enumerate(days) if d[:7] == mo]
        if len(idx) < 3:
            continue
        xs = [ta[i] for i in idx]
        ys = [ba[i] for i in idx]
        c = pearson(xs, ys)
        sd = std([x - y for x, y in zip(xs, ys)])
        fi = idx[0]
        d0 = days[fi - 1] if fi > 0 else days[0]
        d1 = days[idx[-1]]
        mt = cum_ret(tmap, d0, d1)
        mb = cum_ret(bmap, d0, d1)
        diff = (mt - mb) if (mt is not None and mb is not None) else float('nan')
        print(f'  {mo:<11}{c:>9.4f}{sd:>10.4f}%{diff:>+10.2f}%{len(idx):>6}')

    # 阈值回测
    print('\n  ── 用现成阈值回测（连续2天确认）──')
    print(f'  {"窗口":<6}{"阈值":>8}{"触发次数":>10}{"当前偏差":>11}{"最大|偏差|":>11}')
    for L, th in [(3, 1.00), (5, 1.20), (7, 1.40), (10, 1.60)]:
        ser = []
        for i in range(L, len(days)):
            ra = cum_ret(tmap, days[i - L], days[i])
            rbb = cum_ret(bmap, days[i - L], days[i])
            if ra is not None and rbb is not None:
                ser.append(ra - rbb)
        run = trig = 0
        for v in ser:
            run = run + 1 if abs(v) > th else 0
            if run >= 2:
                trig += 1
        cur = ser[-1] if ser else float('nan')
        mxv = max(abs(v) for v in ser) if ser else float('nan')
        print(f'  {L}日{"":<3}{th:>7.2f}%{trig:>9}次{cur:>+10.2f}%{mxv:>10.2f}%')

    return {'corr': corr, 'sdev': sdev, 'te': te, 'cum': ct, 'cumB': cb, 'days': len(days)}


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else '016701'
    since = sys.argv[2] if len(sys.argv) > 2 else None

    print('=' * 68)
    print(f'平替尽调：{code}')
    print('=' * 68)

    t = fetch_nav(code)
    if not t:
        print(f'❌ {code} 无净值数据，请核对代码')
        return 1
    json.dump(t[-KEEP:], open(os.path.join(DATA, f'nav_{code}.json'), 'w',
              encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'\n数据区间：{t[0]["d"]} ~ {t[-1]["d"]}（共 {len(t)} 条）')
    print(f'最新净值：{t[-1]["nav"]}  ({t[-1]["chg"]:+.2f}%)')
    print(f'申购状态：{t[-1]["sg"]}   赎回状态：{t[-1]["sh"]}')
    print('\n近 5 个交易日申购状态：')
    for r in t[-5:]:
        print(f'  {r["d"]}  净值 {r["nav"]:<8} 申购[{r["sg"]}]')

    tmap = {r['d']: r for r in t}
    print('\n拉取基准 270042 ...')
    b = fetch_nav('270042')
    json.dump(b[-KEEP:], open(os.path.join(DATA, 'nav_270042.json'), 'w',
              encoding='utf-8'), ensure_ascii=False, indent=1)
    bmap = {r['d']: r for r in b}

    res = analyze(f'{code} vs 270042（纳指100基准）', tmap, bmap, since)

    # 对照：080006
    print('\n\n拉取对照 080006 ...')
    r6 = fetch_nav('080006')
    json.dump(r6[-KEEP:], open(os.path.join(DATA, 'nav_080006.json'), 'w',
              encoding='utf-8'), ensure_ascii=False, indent=1)
    rmap = {r['d']: r for r in r6}
    analyze('080006 vs 270042（当前在用的平替，作对照）', rmap, bmap, since)

    return 0


if __name__ == '__main__':
    sys.exit(main())
