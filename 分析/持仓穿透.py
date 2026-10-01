# -*- coding: utf-8 -*-
"""持仓穿透 + 费率对比"""
import urllib.request, json, re, time

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}


def get(url, ref=None):
    h = dict(UA)
    if ref:
        h['Referer'] = ref
    return urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                  timeout=30).read().decode('utf-8', 'replace')


for code in ['016701', '080006']:
    print('=' * 62)
    print(f'持仓穿透：{code}')
    print('=' * 62)
    try:
        u = ('https://fundf10.eastmoney.com/FundArchivesDatas.aspx'
             f'?type=jjcc&code={code}&topline=10&year=&month=&rt=0.1')
        t = get(u, f'https://fundf10.eastmoney.com/ccmx_{code}.html')
        m = re.search(r'content:"(.*?)",arryear', t, re.S)
        html = m.group(1) if m else ''
        got = False
        for tr in re.findall(r'<tr>(.*?)</tr>', html, re.S):
            cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', '').strip()
                     for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            if len(cells) >= 5 and cells[0].isdigit():
                print(f'   {cells[0]:>3}. {cells[2]:<14} 占净值 {cells[4]}')
                got = True
        if not got:
            print('   （未取到持仓明细）')
    except Exception as e:
        print('   持仓获取失败:', e)

    try:
        t2 = get(f'https://fundf10.eastmoney.com/jjfl_{code}.html')
        found = False
        for kw in ['管理费率', '托管费率', '销售服务费率', '最高申购费率']:
            mm = re.search(kw + r'[^0-9%]*?([0-9.]+%)', t2)
            if mm:
                print(f'   {kw}: {mm.group(1)}')
                found = True
        if not found:
            print('   （费率未解析到）')
    except Exception as e:
        print('   费率获取失败:', e)
    print()
    time.sleep(1)
