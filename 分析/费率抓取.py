# -*- coding: utf-8 -*-
"""费率抓取"""
import urllib.request, re, time

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=30).read().decode('utf-8', 'replace')


for code in ['016701', '080006', '270042']:
    print('=' * 58)
    print(f'费率：{code}')
    print('=' * 58)
    try:
        t = get(f'https://fundf10.eastmoney.com/jjfl_{code}.html')
        txt = re.sub(r'<script.*?</script>', '', t, flags=re.S)
        txt = re.sub(r'<[^>]+>', '\n', txt)
        txt = re.sub(r'&nbsp;', ' ', txt)
        lines = [l.strip() for l in txt.split('\n') if l.strip()]
        keys = ['管理费率', '托管费率', '销售服务费率', '最高申购费率',
                '最高赎回费率', '申购起点', '首募规模', '成立日期']
        hit = False
        for i, l in enumerate(lines):
            for k in keys:
                if k in l:
                    nxt = ' '.join(lines[i:i + 4])[:110]
                    print(f'   {nxt}')
                    hit = True
                    break
        if not hit:
            print('   （未解析到，页面结构可能不同）')
    except Exception as e:
        print('   失败:', e)
    print()
    time.sleep(1)
