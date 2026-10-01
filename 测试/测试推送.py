# -*- coding: utf-8 -*-
"""
推送通道联通测试 —— 不改动监控数据，只验证能否把消息送到你手机

用法: python 测试推送.py
"""
import json, os, sys, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, '数据', 'notify_config.json')

TITLE = '通道测试 · 基金漂移监控'
BODY = ('这是一条测试消息。\n'
        '收到即代表推送通道正常，触发预警时你能第一时间收到。\n'
        '（无需回复）')

CH_NAME = {'wecom_webhook': '企业微信群机器人', 'serverchan': 'Server酱',
           'pushplus': 'PushPlus', 'none': '未配置'}


def post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))


def main():
    if not os.path.exists(CFG):
        print(f'❌ 配置文件不存在：{CFG}')
        return 1
    cfg = json.load(open(CFG, encoding='utf-8'))
    ch = cfg.get('channel', 'none')
    print(f'当前通道：{ch}（{CH_NAME.get(ch, ch)}）')
    print('-' * 56)

    try:
        if ch == 'serverchan':
            key = cfg.get('serverchan_key', '')
            if not key:
                print('❌ 未配置 serverchan_key')
                return 1
            print(f'SendKey：{key[:12]}...（长度 {len(key)}）')
            url = f'https://sctapi.ftqq.com/{key}.send'
            data = urllib.parse.urlencode({'title': TITLE, 'desp': BODY}).encode()
            r = post(url, data, {'Content-Type': 'application/x-www-form-urlencoded'})
            ok = r.get('code') == 0
            print(f'返回：{json.dumps(r, ensure_ascii=False)}')
            if ok:
                print(f'✅ 推送成功（pushid {r.get("data", {}).get("pushid")}），请查看手机')
            else:
                code = r.get('code')
                hint = {40001: 'SendKey 无效，去 sct.ftqq.com 重新复制',
                        93000: '通道已被删除或停用',
                        45009: '超出当日推送上限（免费版每天5条）'}.get(code, '未知错误')
                print(f'❌ 推送失败：{hint}')

        elif ch == 'wecom_webhook':
            url = cfg.get('wecom_webhook_url', '')
            if not url:
                print('❌ 未配置 wecom_webhook_url')
                return 1
            body = {'msgtype': 'text', 'text': {'content': f'{TITLE}\n\n{BODY}'}}
            r = post(url, json.dumps(body).encode('utf-8'),
                     {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
            ok = r.get('errcode') == 0
            print(f'返回：{json.dumps(r, ensure_ascii=False)}')
            hint = {93000: '机器人已被删除或 webhook 失效',
                    40001: 'key 无效',
                    45009: '接口调用超过限制'}.get(r.get('errcode'), '')
            print(('✅ 推送成功，请查看群消息' if ok else f'❌ 推送失败：{hint}'))

        elif ch == 'pushplus':
            tok = cfg.get('pushplus_token', '')
            if not tok:
                print('❌ 未配置 pushplus_token')
                return 1
            body = {'token': tok, 'title': TITLE, 'content': BODY, 'template': 'txt'}
            r = post('https://www.pushplus.plus/send', json.dumps(body).encode('utf-8'),
                     {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
            ok = r.get('code') == 200
            print(f'返回：{json.dumps(r, ensure_ascii=False)}')
            print(('✅ 推送成功，请查看手机' if ok else '❌ 推送失败，检查 token'))

        else:
            print('⚠️ channel=none，未配置推送通道。')
            print('   请编辑 数据/notify_config.json，把 channel 改为 serverchan 并填入 SendKey。')
            return 0
    except Exception as e:
        print(f'❌ 测试失败：{e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
