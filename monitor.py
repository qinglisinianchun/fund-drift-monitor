# -*- coding: utf-8 -*-
"""
基金漂移监控 —— 判断 080006 是否还配当纳指100平替

背景
----
270042 广发纳斯达克100ETF联接(QDII)A 因限额限购，额度稀缺。
080006 长盛环球行业混合(QDII)A 经观察持仓与纳指100高度重合，暂作平替。
风险：080006 是主动混合基金，基金经理有权换仓。一旦大举买入非纳指标的，
      走势将与 270042 脱钩。本脚本用两基金净值偏差做「漂移探测器」。

阈值校准依据（只用「真对齐期」2026-07-01 起，60 个交易日）
--------------------------------------------------------
重要：080006 并非一直复制纳指。实测逐月相关性：
  2026-06  相关系数 0.924  日偏差 std 0.836%  月收益差 +5.11%  ← 尚未对齐
  2026-07  相关系数 0.997  日偏差 std 0.105%  月收益差 -0.23%
  2026-08  相关系数 0.998  日偏差 std 0.153%  月收益差 +0.37%
  2026-09  相关系数 0.9996 日偏差 std 0.075%  月收益差 +0.03%
故校准区间取 2026-07-01 之后，避免被「未对齐时期」污染而放宽阈值。

对齐期各窗口偏差标准差：
  3日 0.2005%   5日 0.2589%   7日 0.3278%   10日 0.4074%

定稿阈值（≈3σ 以上，连续 2 天确认）：
  窗口   阈值     连续   对齐期误报   漂移期(2026-06)检出
  3日    1.00%    2天    0 次        2 次
  5日    1.20%    2天    0 次        3 次
  7日    1.40%    2天    0 次        2 次
 10日    1.60%    2天    0 次        1 次

红灯预警线（任一窗口单次突破即报，不需连续）
  3日 2.0% / 5日 2.2% / 7日 2.5% / 10日 3.0%

补跑机制
--------
每次运行都会全量拉取净值并与本地缓存合并，自动补齐上次运行以来
落下的所有交易日。补跑情况记录在 latest.json 的 backfill 字段，
并在报告与推送中标出。

输出
----
  数据/nav_*.json      净值缓存（滚动保留）
  数据/latest.json     最新巡检状态（含历史序列，供看板渲染）
  数据/trigger.json    仅触发时生成，供自动化读取并推送微信
  日志/YYYY-MM-DD.md   每日明细（append）
"""

import urllib.request
import json, os, sys, time, datetime, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, '数据')
LOGDIR = os.path.join(BASE, '日志')
for d in (DATA, LOGDIR):
    os.makedirs(d, exist_ok=True)

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}

FUND_A = '080006'   # 长盛环球行业混合(QDII)A —— 纳指平替（被监控对象）
FUND_B = '270042'   # 广发纳斯达克100ETF联接(QDII)人民币A —— 基准

# 窗口: (天数, 阈值%, 连续确认天数)  —— 依 2026-07 起「真对齐期」按 ~3σ 校准
WINDOWS = [(3, 1.00, 2), (5, 1.20, 2), (7, 1.40, 2), (10, 1.60, 2)]
# 红灯预警线（单次突破即报）
ALERT = {3: 2.0, 5: 2.2, 7: 2.5, 10: 3.0}
# 保留交易日数（供看板最长一年；随时间自然积累）
KEEP = 260
# 有效监控起点：080006 在此之前与纳指不重合（实测 2026-06 相关系数仅 0.924），
# 比较无意义，故所有统计、看板展示一律从此日之后取数。
VALID_FROM = '2026-07-01'


def fetch_nav(code, pages=20):
    """东财 f10 历史净值，每页固定 20 条。"""
    rows = []
    for p in range(1, pages + 1):
        url = ('https://api.fund.eastmoney.com/f10/lsjz'
               f'?fundCode={code}&pageIndex={p}&pageSize=20')
        req = urllib.request.Request(url, headers={
            **UA, 'Referer': f'https://fundf10.eastmoney.com/jjjz_{code}.html'})
        data = None
        for attempt in range(3):
            try:
                raw = urllib.request.urlopen(req, timeout=25).read().decode('utf-8')
                data = json.loads(raw)
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f'{code} 第{p}页抓取失败: {e}')
                time.sleep(2)
        lst = (data.get('Data') or {}).get('LSJZList') or []
        if not lst:
            break
        for r in lst:
            rows.append({
                'd': r['FSRQ'],
                'nav': float(r['DWJZ']),
                'chg': float(r['JZZZL']) if r.get('JZZZL') not in (None, '') else None,
                'sg': r.get('SGZT', ''),
                'sh': r.get('SHZT', ''),
            })
        time.sleep(0.7)
    seen, out = set(), []
    for r in rows:
        if r['d'] in seen:
            continue
        seen.add(r['d'])
        out.append(r)
    out.sort(key=lambda x: x['d'])
    return out


def merge_history(code, fresh):
    """合并本地缓存与最新数据，返回 (合并结果, 新增日期列表)"""
    path = os.path.join(DATA, f'nav_{code}.json')
    old = []
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding='utf-8'))
        except Exception:
            old = []
    old_dates = {r['d'] for r in old}
    m = {r['d']: r for r in old}
    new_dates = []
    for r in fresh:
        if r['d'] not in old_dates:
            new_dates.append(r['d'])
        m[r['d']] = r
    merged = sorted(m.values(), key=lambda x: x['d'])[-KEEP:]
    json.dump(merged, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return merged, sorted(new_dates)


def rolling_dev(ma, mb, days, L):
    out = []
    for i in range(L, len(days)):
        d = days[i]
        ra = ma[d] / ma[days[i - L]] - 1
        rb = mb[d] / mb[days[i - L]] - 1
        out.append((d, (ra - rb) * 100))
    return out


def brief(dates, limit=6):
    """日期列表摘要显示，避免刷屏"""
    if not dates:
        return '无'
    if len(dates) <= limit:
        return ', '.join(dates)
    return f'{dates[0]} ~ {dates[-1]}（共 {len(dates)} 个交易日）'


def main():
    now = datetime.datetime.now()
    today = now.strftime('%Y-%m-%d')
    rep = {'run_at': now.strftime('%Y-%m-%d %H:%M:%S'), 'date': today,
           'ok': False, 'triggers': [], 'alerts': [], 'windows': [],
           'backfill': [], 'error': None}
    try:
        A, newA = merge_history(FUND_A, fetch_nav(FUND_A))
        B, newB = merge_history(FUND_B, fetch_nav(FUND_B))
        ma = {r['d']: r['nav'] for r in A}
        mb = {r['d']: r['nav'] for r in B}
        allday = sorted(set(ma) & set(mb))
        # 只从有效起点之后比较（7/1 之前与纳指不重合，比较无意义）
        days = [d for d in allday if d >= VALID_FROM]
        need_min = max(w[0] for w in WINDOWS) + 2
        if len(days) < need_min:
            raise RuntimeError(f'有效交易日不足（{len(days)} < {need_min}，起点 {VALID_FROM}）')

        latestA, latestB = A[-1], B[-1]
        rep['latest'] = {
            'A': {k: latestA[k] for k in ('d', 'nav', 'chg', 'sg', 'sh')},
            'B': {k: latestB[k] for k in ('d', 'nav', 'chg', 'sg', 'sh')},
        }
        rep['range'] = f'{days[0]} ~ {days[-1]}（{len(days)}个交易日）'
        rep['valid_from'] = VALID_FROM

        # 补跑检测：找出「上次运行日」与「本次最新净值日」之间漏掉的交易日
        last_run_file = os.path.join(DATA, 'last_run.txt')
        prev_run = None
        if os.path.exists(last_run_file):
            prev_run = open(last_run_file, encoding='utf-8').read().strip()
        cur_date = latestA['d']
        if prev_run:
            # 上次记录日之后、本次最新日之前的日子 = 关机期间漏掉的
            rep['backfill'] = [d for d in days if prev_run < d < cur_date]
            rep['new_dates'] = [cur_date] if cur_date > prev_run else []
        else:
            rep['backfill'] = []
            rep['new_dates'] = []
            rep['first_run'] = True
        rep['prev_run'] = prev_run
        open(last_run_file, 'w', encoding='utf-8').write(cur_date)

        d1 = [(days[i], (ma[days[i]] / ma[days[i-1]] - mb[days[i]] / mb[days[i-1]]) * 100)
              for i in range(1, len(days))]

        for L, th, need in WINDOWS:
            s = rolling_dev(ma, mb, days, L)
            if not s:
                continue
            run = 0
            for _, v in s:
                run = run + 1 if abs(v) > th else 0
            cur = s[-1][1]
            hit = run >= need
            rep['windows'].append({
                'window': L, 'threshold': th, 'need_days': need,
                'current_dev': round(cur, 4), 'hit_run': run, 'triggered': bool(hit)})
            if hit:
                rep['triggers'].append(
                    f'{L}日滚动偏差 {cur:+.2f}%（阈值±{th}%）已连续 {run} 天超限')
            if abs(cur) > ALERT[L]:
                rep['alerts'].append(
                    f'{L}日滚动偏差 {cur:+.2f}% 突破预警线 ±{ALERT[L]}%')

        rep['daily_dev'] = {'current': round(d1[-1][1], 4),
                            'series': [[d, round(v, 4)] for d, v in d1]}

        # 供看板渲染的完整序列（归一化后由前端算，这里给原始值）
        rep['series'] = {
            'dates': days,
            'A': [round(ma[d], 4) for d in days],
            'B': [round(mb[d], 4) for d in days],
        }
        # 各窗口滚动偏差完整序列
        rep['dev_series'] = {
            str(L): [[d, round(v, 4)] for d, v in rolling_dev(ma, mb, days, L)]
            for L, _, _ in WINDOWS
        }
        rep['ok'] = True
    except Exception as e:
        rep['error'] = f'{e}\n{traceback.format_exc()}'

    json.dump(rep, open(os.path.join(DATA, 'latest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)

    trig = os.path.join(DATA, 'trigger.json')
    if rep['triggers'] or rep['alerts']:
        json.dump(rep, open(trig, 'w', encoding='utf-8'), ensure_ascii=False)
    elif os.path.exists(trig):
        os.remove(trig)

    with open(os.path.join(LOGDIR, f'{today}.md'), 'a', encoding='utf-8') as f:
        f.write(f'\n## {now.strftime("%H:%M:%S")} 巡检\n\n')
        if not rep['ok']:
            f.write(f'- ❌ 执行失败：{rep["error"]}\n')
        else:
            la, lb = rep['latest']['A'], rep['latest']['B']
            if rep['new_dates']:
                f.write(f'- 📥 新拉取净值：{brief(rep["new_dates"])}\n')
            if rep['backfill']:
                f.write(f'- 🔄 补跑历史：{brief(rep["backfill"])}\n')
            else:
                f.write(f'- ℹ️ 无补跑（上次运行后无遗漏交易日）\n')
            f.write(f'- 080006 净值 {la["nav"]}（{la["chg"]}%，{la["d"]}，{la["sg"]}）\n')
            f.write(f'- 270042 净值 {lb["nav"]}（{lb["chg"]}%，{lb["d"]}，{lb["sg"]}）\n')
            f.write(f'- 当日偏差 {rep["daily_dev"]["current"]:+.4f}%\n')
            for w in rep['windows']:
                flag = '🔴触发' if w['triggered'] else '✅正常'
                f.write(f'- {w["window"]}日偏差 {w["current_dev"]:+.4f}%'
                        f'（阈值±{w["threshold"]}%，连续 {w["hit_run"]}/{w["need_days"]} 天）{flag}\n')
            for t in rep['triggers']:
                f.write(f'- ⚠️ {t}\n')
            for a in rep['alerts']:
                f.write(f'- 🚨 {a}\n')

    print('=' * 64)
    if not rep['ok']:
        print('❌ 巡检失败:', rep['error'].splitlines()[0])
        return 2
    la, lb = rep['latest']['A'], rep['latest']['B']
    print(f'巡检 {rep["run_at"]}   数据区间 {rep["range"]}')
    if rep['new_dates']:
        print(f'  📥 本次新拉到：{brief(rep["new_dates"])}')
    if rep['backfill']:
        print(f'  🔄 补跑落下的交易日：{brief(rep["backfill"])}')
    print(f'  080006  {la["nav"]:>8} ({la["chg"]:+.2f}%)  {la["d"]}  {la["sg"]}')
    print(f'  270042  {lb["nav"]:>8} ({lb["chg"]:+.2f}%)  {lb["d"]}  {lb["sg"]}')
    print(f'  当日偏差 {rep["daily_dev"]["current"]:+.4f}%')
    for w in rep['windows']:
        flag = '🔴 触发' if w['triggered'] else '✅ 正常'
        print(f'  {w["window"]:>2}日偏差 {w["current_dev"]:+7.3f}%  '
              f'(阈值±{w["threshold"]}%  连续{w["hit_run"]}/{w["need_days"]})  {flag}')
    for t in rep['triggers']:
        print('  ⚠️ ', t)
    for a in rep['alerts']:
        print('  🚨 ', a)
    print('=' * 64)
    return 1 if (rep['triggers'] or rep['alerts']) else 0


if __name__ == '__main__':
    sys.exit(main())
