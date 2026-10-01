# -*- coding: utf-8 -*-
"""用 Edge CDP 实测看板：纵轴百分比 + 起点0% + 悬停提示框"""
import json, base64, socket, struct, os, urllib.request, urllib.parse
from urllib.parse import urlparse

PORT = 9335


def ws_connect(url):
    u = urlparse(url)
    s = socket.create_connection((u.hostname, u.port), timeout=15)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf = b''
    while b'\r\n\r\n' not in buf:
        buf += s.recv(4096)
    return s


def ws_send(s, obj):
    data = json.dumps(obj).encode()
    hdr = bytearray([0x81])
    n = len(data)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126); hdr += struct.pack('>H', n)
    else:
        hdr.append(0x80 | 127); hdr += struct.pack('>Q', n)
    mask = os.urandom(4)
    hdr += mask
    s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def ws_recv(s):
    def rd(n):
        b = b''
        while len(b) < n:
            c = s.recv(n - len(b))
            if not c:
                raise IOError('closed')
            b += c
        return b
    h = rd(2)
    ln = h[1] & 0x7f
    if ln == 126:
        ln = struct.unpack('>H', rd(2))[0]
    elif ln == 127:
        ln = struct.unpack('>Q', rd(8))[0]
    return rd(ln).decode('utf-8', 'replace')


pb = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tabs = json.loads(pb.open(f'http://127.0.0.1:{PORT}/json/list', timeout=10).read())
cand = [t for t in tabs if t['type'] == 'page' and '看板' in urllib.parse.unquote(t.get('url', ''))]
page = cand[0] if cand else [t for t in tabs if t['type'] == 'page'][-1]
s = ws_connect(page['webSocketDebuggerUrl'])
_id = [0]


def ev(expr):
    _id[0] += 1
    ws_send(s, {'id': _id[0], 'method': 'Runtime.evaluate',
                'params': {'expression': expr, 'returnByValue': True}})
    while True:
        m = json.loads(ws_recv(s))
        if m.get('id') == _id[0]:
            r = m.get('result', {})
            if 'exceptionDetails' in r:
                return 'ERR: ' + str(r['exceptionDetails'].get('text', ''))
            return r.get('result', {}).get('value')


def js(body):
    return "(function(){" + body + "})()"


print('=== 1) 纵轴刻度（应为百分比） ===')
print(ev(js("var s=document.getElementById('chartNav');"
            "return Array.prototype.slice.call(s.querySelectorAll('text'))"
            ".map(function(t){return t.textContent;}).join(' | ');")))

print('\n=== 2) 起点是否 0%，各范围验证 ===')
for rk in ['1m', '3m']:
    q = js(
        "var btns=Array.prototype.slice.call(document.querySelectorAll('#seg button'));"
        "var b=btns.filter(function(x){return x.dataset.r===" + json.dumps(rk) + ";})[0];"
        "if(!b) return 'no button';"
        "b.click();"
        "return JSON.stringify({r:" + json.dumps(rk) + ",n:NAVCTX.n,"
        "A首:NAVCTX.av[0],B首:NAVCTX.bv[0],"
        "A末:NAVCTX.av[NAVCTX.n-1],B末:NAVCTX.bv[NAVCTX.n-1],"
        "首日:NAVCTX.dts[0],末日:NAVCTX.dts[NAVCTX.n-1],"
        "纵轴:Array.prototype.slice.call(document.getElementById('chartNav')"
        ".querySelectorAll('text')).filter(function(t){return t.textContent.indexOf('%')>=0;})"
        ".map(function(t){return t.textContent;}).join(' ')});")
    print('  ' + str(ev(q)))

print('\n=== 3) 悬停中部 ===')
print('  ' + str(ev(js(
    "var svg=document.getElementById('chartNav');var r=svg.getBoundingClientRect();"
    "svg.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+r.width*0.5,"
    "clientY:r.top+r.height*0.45,bubbles:true}));"
    "var t=document.querySelector('#crh .tipbox');"
    "return JSON.stringify({显示:document.getElementById('crh').classList.contains('on'),"
    "文本:t?t.innerText.replace(/\\n/g,' / '):null,"
    "竖线:document.querySelector('#crh .vline')?document.querySelector('#crh .vline').style.left:null});"))))

print('\n=== 4) 悬停起点（应标"（起点）"且 0.00%） ===')
print('  ' + str(ev(js(
    "var svg=document.getElementById('chartNav');var r=svg.getBoundingClientRect();"
    "svg.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+r.width*0.065,"
    "clientY:r.top+60,bubbles:true}));"
    "var t=document.querySelector('#crh .tipbox');"
    "return t?t.innerText.replace(/\\n/g,' / '):'无';"))))

print('\n=== 5) 悬停终点 ===')
print('  ' + str(ev(js(
    "var svg=document.getElementById('chartNav');var r=svg.getBoundingClientRect();"
    "svg.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+r.width*0.985,"
    "clientY:r.top+60,bubbles:true}));"
    "var t=document.querySelector('#crh .tipbox');"
    "return t?t.innerText.replace(/\\n/g,' / '):'无';"))))

print('\n=== 6) 移出应隐藏 ===')
print('  ' + str(ev(js(
    "document.getElementById('chartNav').dispatchEvent(new MouseEvent('mouseleave',{bubbles:true}));"
    "return document.getElementById('crh').classList.contains('on');"))))

print('\n=== 7) 图②刻度与零轴 ===')
print('  ' + str(ev(js(
    "var s=document.getElementById('chartDev');"
    "var tx=Array.prototype.slice.call(s.querySelectorAll('text')).map(function(t){return t.textContent;});"
    "var zl=Array.prototype.slice.call(s.querySelectorAll('line')).filter(function(l){"
    "return l.getAttribute('stroke')==='#d8dbe0';});"
    "return JSON.stringify({刻度:tx,零轴:zl.length>0});"))))

print('\n=== 8) 起点圆点与零轴 ===')
print('  ' + str(ev(js(
    "var s=document.getElementById('chartNav');"
    "var c=s.querySelectorAll('circle').length;"
    "var zl=Array.prototype.slice.call(s.querySelectorAll('line')).filter(function(l){"
    "return l.getAttribute('stroke')==='#c9ced5';}).length;"
    "return JSON.stringify({起点圆点:c,零轴:zl});"))))

s.close()
