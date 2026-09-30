# -*- coding: utf-8 -*-
"""
微信提醒推送 —— 读取 数据/trigger.json，推送到指定通道

设计
----
通道可插拔，配置文件 数据/notify_config.json：

{
  "channel": "wecom_webhook",        // wecom_webhook | serverchan | pushplus | none
  "wecom_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
  "serverchan_key": "SCTxxxx",
  "pushplus_token": "xxxx",
  "mention_all": true,
  "at_mobiles": []
}

- channel=wecom_webhook：企业微信群机器人（最简单，手机端企业微信/微信都能收到）
- channel=serverchan  ：Server酱，直推个人微信（需在 sct.ftqq.com 拿 key）
- channel=pushplus    ：PushPlus，直推个人微信（需在 pushplus.plus 拿 token）
- channel=none        ：只写本地日志，不推送（默认）

密钥从哪来
----------
优先读环境变量，其次读 数据/notify_config.json（叠加，不是替换）：

  NOTIFY_CHANNEL       → channel
  WECOM_WEBHOOK_URL    → wecom_webhook_url
  SERVERCHAN_KEY       → serverchan_key
  PUSHPLUS_TOKEN       → pushplus_token

这样仓库里提交的 notify_config.json 可以只留通道名、密钥留空，
真值放在 GitHub Actions 的 Secrets 里 —— 公开仓库也不会泄露密钥。

未配置或推送失败时，不抛异常——只把结果写日志，绝不因推送问题影响监控本身。

用法
----
- python3 notify.py          # 预警模式：仅当 trigger.json 存在（触发漂移）时推送
- python3 notify.py weekly   # 周报模式：无论是否漂移，汇总最近一个交易周并推送（每周日用）
"""

import json, os, sys, urllib.request, urllib.error, urllib.parse
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, '数据')
LOGDIR = os.path.join(BASE, '日志')
CFG = os.path.join(DATA, 'notify_config.json')
TRIG = os.path.join(DATA, 'trigger.json')

UA = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}

# 红灯预警线（与 monitor.py 的 ALERT 一致）
ALERT_LINE = {3: 2.0, 5: 2.2, 7: 2.5, 10: 3.0}


# 环境变量 → 配置字段映射。
# 用途：仓库里的 数据/notify_config.json 只放「占位」（密钥留空），
#       真值从环境变量注入（GitHub Actions 用 Secrets、本地用 export）。
# 说明：这里做的是「叠加」而不是「替换」——没设环境变量时，
#       仍旧读 JSON 里的值，所以本地把密钥写在 JSON 里照样能跑。
ENV_KEYS = {
    'NOTIFY_CHANNEL':    'channel',
    'WECOM_WEBHOOK_URL': 'wecom_webhook_url',
    'SERVERCHAN_KEY':    'serverchan_key',
    'PUSHPLUS_TOKEN':    'pushplus_token',
}


def load_cfg():
    if not os.path.exists(CFG):
        cfg = {'channel': 'none'}
    else:
        try:
            cfg = json.load(open(CFG, encoding='utf-8'))
        except Exception:
            cfg = {'channel': 'none'}
    for env_name, key in ENV_KEYS.items():
        v = os.environ.get(env_name)
        if v and v.strip():
            cfg[key] = v.strip()
    return cfg


def build_text(rep, plain=False):
    """构造提醒正文（精简版：一屏看完）"""
    la, lb = rep['latest']['A'], rep['latest']['B']
    lines = [
        f"🚨 080006 漂移预警 · {rep['date']}",
        '',
        f"080006  {la['nav']}  {la['chg']:+.2f}%",
        f"270042  {lb['nav']}  {lb['chg']:+.2f}%",
    ]

    # 补跑提示（只在有补跑时显示，一行内）
    bf = rep.get('backfill') or []
    if bf:
        s = f'{len(bf)}天（{bf[0]}~{bf[-1]}）' if len(bf) > 2 else '、'.join(bf)
        lines.append(f'含补跑 {s}')

    # 只列出异常窗口：破红灯线 或 连续触发 或 单日超阈
    def is_hot(w):
        return (w['triggered']
                or abs(w['current_dev']) > ALERT_LINE.get(w['window'], 99)
                or abs(w['current_dev']) > w['threshold'])
    bad = [w for w in rep['windows'] if is_hot(w)]
    if bad:
        lines.append('')
        for w in bad:
            red = (w['triggered']
                   or abs(w['current_dev']) > ALERT_LINE.get(w['window'], 99))
            mark = '🔴' if red else '🟡'
            if w['triggered']:
                extra = f" 连续{w['hit_run']}/{w['need_days']}天"
            elif abs(w['current_dev']) > ALERT_LINE.get(w['window'], 99):
                extra = ' 破红灯线'
            else:
                extra = f" 连续{w['hit_run']}/{w['need_days']}天"
            lines.append(f"{mark} {w['window']}日 {w['current_dev']:+.2f}%"
                         f"（阈值±{w['threshold']}%）{extra}")
        rest = [w for w in rep['windows'] if w not in bad]
        if rest:
            lines.append('  ' + ' / '.join(
                f"{w['window']}日{w['current_dev']:+.2f}%" for w in rest) + '  正常')

    # 红灯（单独强调）
    if rep['alerts']:
        lines.append('')
        lines.append('🚨 红灯：' + rep['alerts'][0])

    # 结论：一行
    lines += [
        '',
        '可能是它开始调仓、不再是纳指平替。',
        '建议查持仓公告确认，必要时换回被动指数。',
    ]
    return '\n'.join(lines)


def build_weekly(rep):
    """构造每周例行报告（无论是否漂移都推送）。

    口径：以「最新净值日」所在周的周一为起点、最新净值日为终点，
    覆盖刚结束的这个交易周（周日运行即周一~周五）。正文标注明确日期范围。
    返回 (正文, 简短标题)。
    """
    daily = (rep.get('daily_dev') or {}).get('series') or []
    if not daily:
        raise RuntimeError('latest.json 中无 daily_dev 序列，无法生成周报')

    latest_d_str = rep['latest']['A']['d']
    latest_d = datetime.date.fromisoformat(latest_d_str)
    monday = (latest_d - datetime.timedelta(days=latest_d.weekday())).isoformat()

    # 本周一 ~ 最新净值日 的当日偏差
    week = [(d, v) for d, v in daily if monday <= d <= latest_d_str]
    if not week:  # 兜底：取最近 5 条
        week = daily[-5:]
    d0, d1 = week[0][0], week[-1][0]
    vals = [v for _, v in week]
    avg, mx, mn = sum(vals) / len(vals), max(vals), min(vals)

    # 各窗口：周末值 + 周内峰值
    dev_series = rep.get('dev_series') or {}
    win_lines, week_peak, week_red = [], 0.0, False
    for w in rep['windows']:
        L, thr = w['window'], w['threshold']
        redline = ALERT_LINE.get(L, 99)
        sw = [(d, v) for d, v in dev_series.get(str(L), [])
              if monday <= d <= latest_d_str]
        if sw:
            end_v, peak = sw[-1][1], max(abs(v) for _, v in sw)
        else:
            end_v, peak = w['current_dev'], abs(w['current_dev'])
        week_peak = max(week_peak, peak)
        if peak > redline:
            week_red = True
        if peak > redline:
            mark = '🔴'
        elif peak > thr:
            mark = '🟡'
        else:
            mark = '✅'
        win_lines.append(
            f"{mark} {L:>2}日  周末{end_v:+.2f}% / 周内峰值{peak:.2f}%"
            f"（阈值±{thr}%，红线±{redline}%）")

    la, lb = rep['latest']['A'], rep['latest']['B']
    cur_bad = bool(rep.get('triggers') or rep.get('alerts'))
    span = f'{d0[5:].replace("-", "/")}~{d1[5:].replace("-", "/")}'
    title = f'080006 漂移周报 {span}'

    if week_red or cur_bad:
        head = f"🚨 080006 漂移周报 · {span}"
        tail = ['', '⚠️ 本周偏差曾明显放大或突破红线，可能已开始调仓。',
                '建议查持仓公告确认，必要时换回被动指数。']
    elif week_peak > min(w['threshold'] for w in rep['windows']):
        head = f"🟡 080006 漂移周报 · {span}"
        tail = ['', '🟡 本周偏差略有放大但未连续确认，保持观察，下周周报继续跟踪。']
    else:
        head = f"📋 080006 漂移周报 · {span}"
        tail = ['', f'✅ 本周（{len(week)}个交易日）两基金走势贴合、偏差平稳，',
                '080006 仍是纳指100平替，监控运行正常。']

    lines = [head, '',
             f'区间 {d0} ~ {d1}（{len(week)}个交易日）',
             f'080006  {la["nav"]}  {la["chg"]:+.2f}%',
             f'270042  {lb["nav"]}  {lb["chg"]:+.2f}%', '',
             f'当日偏差  平均{avg:+.3f}%  最大{mx:+.3f}%  最小{mn:+.3f}%', '',
             '各窗口（周末值 / 周内峰值）：']
    lines += win_lines
    if rep.get('alerts'):
        lines += ['', '本周红灯记录：'] + [f'🚨 {a}' for a in rep['alerts']]
    if rep.get('triggers'):
        lines += ['', '本周黄灯记录：'] + [f'🟡 {t}' for t in rep['triggers']]
    lines += tail
    return '\n'.join(lines), title


def push_wecom(url, text, cfg):
    body = {'msgtype': 'text', 'text': {'content': text}}
    mobiles = [m for m in (cfg.get('at_mobiles') or []) if m]
    if cfg.get('mention_all'):
        body['text']['mentioned_list'] = ['@all']
    elif mobiles:
        body['text']['mentioned_list'] = mobiles
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=UA)
    r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
    return r.get('errcode') == 0, r


def push_serverchan(key, text, title='080006 漂移预警'):
    url = f'https://sctapi.ftqq.com/{key}.send'
    data = urllib.parse.urlencode({'title': title, 'desp': text}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
    return r.get('code') == 0, r


def push_pushplus(token, text, title='080006 漂移预警'):
    url = 'https://www.pushplus.plus/send'
    body = {'token': token, 'title': title, 'content': text, 'template': 'txt'}
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=UA)
    r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
    return r.get('code') == 200, r


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'alert'
    cfg = load_cfg()
    ch = cfg.get('channel', 'none')

    if mode == 'weekly':
        latest_path = os.path.join(DATA, 'latest.json')
        if not os.path.exists(latest_path):
            print('周报生成失败：数据/latest.json 不存在，请先运行 monitor.py')
            return 1
        rep = json.load(open(latest_path, encoding='utf-8'))
        text, title = build_weekly(rep)
        kind_label = '每周周报'
    else:
        if not os.path.exists(TRIG):
            print('无待推送内容（未触发）')
            return 0
        rep = json.load(open(TRIG, encoding='utf-8'))
        text = build_text(rep)
        title = '080006 漂移预警'
        kind_label = '漂移预警'

    ok, detail = False, 'skipped'
    try:
        if ch == 'wecom_webhook':
            url = cfg.get('wecom_webhook_url', '')
            if not url:
                raise RuntimeError('未配置 wecom_webhook_url')
            ok, detail = push_wecom(url, text, cfg)
        elif ch == 'serverchan':
            k = cfg.get('serverchan_key', '')
            if not k:
                raise RuntimeError('未配置 serverchan_key')
            ok, detail = push_serverchan(k, text, title)
        elif ch == 'pushplus':
            k = cfg.get('pushplus_token', '')
            if not k:
                raise RuntimeError('未配置 pushplus_token')
            ok, detail = push_pushplus(k, text, title)
        else:
            detail = 'channel=none，仅记录日志'
    except Exception as e:
        ok, detail = False, f'推送异常: {e}'

    # 日志
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, f'{today}.md'), 'a', encoding='utf-8') as f:
        f.write(f'\n### 微信推送（{ch} · {kind_label}）\n\n')
        f.write(f'- 结果：{"✅成功" if ok else "⚠️未成功"} — {detail}\n')
        f.write('\n```\n' + text + '\n```\n')

    print(f'[{ch} · {kind_label}] {"✅ 推送成功" if ok else "⚠️ " + str(detail)}')
    if not ok:
        print('\n--- 内容正文 ---')
        print(text)
    return 0   # 推送失败不阻断


if __name__ == '__main__':
    sys.exit(main())
