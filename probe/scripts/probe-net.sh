#!/usr/bin/env bash
# =============================================================================
# 探测：GitHub Actions 的 runner 能不能访问「纳指平替漂移监控」所需的全部外部接口
#
# 这是把监控搬上 GitHub 之前必须过的一关。本机（走 VPN）能访问，
# 不代表 GitHub 的机器（多在境外）能访问。达不成就白搭。
#
# 只探测，不产生副作用：Server酱 那项故意用**假 key**，
# 目的是看接口会不会返回正常的业务错误 JSON —— 能返回业务错误，
# 就说明网络通、没被地域拦截，同时不会真的往你微信发消息。
# =============================================================================
set -uo pipefail

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
BODIES=/tmp/probe_bodies
SUMMARY=/tmp/probe_summary.txt
mkdir -p "$BODIES"
: > "$SUMMARY"

hr() { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

record() { printf '%-26s %-6s %s\n' "$1" "$2" "$3" >> "$SUMMARY"; }

# probe <存档名> <显示名> <URL> [Referer]
#   · 自动跟随 301/302（上一轮就是栽在这：基金代码表是 http 跳 https）
#   · 打印最终 URL、各阶段耗时
probe() {
  local slug="$1" name="$2" url="$3" ref="${4-}"
  local out="$BODIES/$slug.body"
  local hdr=(-A "$UA")
  [ -n "$ref" ] && hdr+=(-H "Referer: $ref")

  hr
  printf '▸ %s\n  %s\n' "$name" "$url"

  local meta rc
  meta=$(curl -sS -L --max-redirs 5 -m 45 -o "$out" \
        -w 'HTTP %{http_code} | %{size_download} B | DNS %{time_namelookup}s | TLS %{time_appconnect}s | 共 %{time_total}s | 重定向%{num_redirects}次' \
        "${hdr[@]}" "$url" 2>&1); rc=$?
  printf '  %s\n' "$meta"

  if [ "$rc" -ne 0 ]; then
    printf '  ❌ curl 退出码 %s —— 连接层就失败了\n' "$rc"
    record "$name" "FAIL" "curl rc=$rc"
    return 1
  fi

  local code="${meta#HTTP }"; code="${code%% *}"
  printf '  ── 响应前 160 字节 ──\n  '
  head -c 160 "$out" 2>/dev/null | tr -d '\n'
  printf '\n'

  if [ "$code" = "200" ]; then
    record "$name" "OK" "HTTP 200 · $(wc -c < "$out") B"
  else
    record "$name" "WARN" "HTTP $code"
  fi
  return 0
}

# -----------------------------------------------------------------------------
echo "【0】运行环境"
hr
echo "  os     : $(uname -srm)"
echo "  python : $(python3 -V 2>&1)"
ipinfo=$(curl -sS -m 25 https://ipinfo.io/json 2>/dev/null || true)
if [ -n "$ipinfo" ]; then
  echo "  出口 IP: $(printf '%s' "$ipinfo" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("ip"),"|",d.get("city"),d.get("region"),d.get("country"),"|",d.get("org"))' 2>/dev/null || echo 解析失败)"
fi
echo

# -----------------------------------------------------------------------------
echo "【1】东方财富 · 历史净值接口 —— 监控的命脉（连测 3 次看稳定性）"
for i in 1 2 3; do
  probe "navA$i" "净值 080006 第${i}次" \
    "https://api.fund.eastmoney.com/f10/lsjz?fundCode=080006&pageIndex=1&pageSize=20" \
    "https://fundf10.eastmoney.com/jjjz_080006.html"
done
probe navB "净值 270042" \
  "https://api.fund.eastmoney.com/f10/lsjz?fundCode=270042&pageIndex=1&pageSize=20" \
  "https://fundf10.eastmoney.com/jjjz_270042.html"
# 深页：一次要拉 20 页，测第 20 页也在不在
probe navA20 "净值 080006 第20页" \
  "https://api.fund.eastmoney.com/f10/lsjz?fundCode=080006&pageIndex=20&pageSize=20" \
  "https://fundf10.eastmoney.com/jjjz_080006.html"

# -----------------------------------------------------------------------------
echo "【2】基金代码全表（http 明文 → 会跳 https，必须跟随重定向）"
probe codes "基金代码表" "https://fund.eastmoney.com/js/fundcode_search.js"

# -----------------------------------------------------------------------------
echo "【3】持仓穿透与费率页（上一轮 404 是我漏了 Referer，这次补上）"
probe hold "持仓 080006" \
  "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=080006&topline=10&year=&month=&rt=0.1" \
  "https://fundf10.eastmoney.com/ccmx_080006.html"
probe fee "费率 080006" "https://fundf10.eastmoney.com/jjfl_080006.html"

# -----------------------------------------------------------------------------
echo "【4】微信推送通道 Server酱 —— 用假 key 打真实发送接口"
echo "    能返回业务错误 = 网络通、没被地域拦；不会真的发消息"
hr
sct_out="$BODIES/sct.body"
sct_meta=$(curl -sS -m 40 -o "$sct_out" \
  -w 'HTTP %{http_code} | %{size_download} B | 共 %{time_total}s' \
  -A "$UA" -X POST \
  "https://sctapi.ftqq.com/SCT000000thisIsAFakeKeyForProbe.send?title=probe" 2>&1); sct_rc=$?
printf '  %s\n' "$sct_meta"
if [ "$sct_rc" -eq 0 ]; then
  printf '  ── 响应 ──\n  '; head -c 300 "$sct_out" | tr -d '\n'; printf '\n'
  record "Server酱 发送接口" "OK" "$(head -c 120 "$sct_out" | tr -d '\n')"
else
  printf '  ❌ curl 退出码 %s\n' "$sct_rc"
  record "Server酱 发送接口" "FAIL" "curl rc=$sct_rc"
fi

# -----------------------------------------------------------------------------
echo "【5】对照组（证明 runner 本身有正常外网）"
probe gh "对照组 github" "https://api.github.com"

# -----------------------------------------------------------------------------
echo
hr
echo "▸ 内容校验 —— 200 也可能是被拦后返回的空壳页，必须验真数据"
python3 - "$BODIES" <<'PY'
import json, os, re, sys
B = sys.argv[1]

def body(slug):
    p = os.path.join(B, slug + '.body')
    return open(p, encoding='utf-8', errors='replace').read() if os.path.exists(p) else None

def nav(slug):
    raw = body(slug)
    if raw is None:
        return False, '无响应'
    s = raw.lstrip()
    if not s.startswith('{'):
        return False, f'不是 JSON，开头：{s[:70]!r}'
    try:
        d = json.loads(raw)
    except Exception as e:
        return False, f'JSON 解析失败：{e}'
    lst = ((d.get('Data') or {}).get('LSJZList')) or []
    if not lst:
        return False, f'LSJZList 为空；顶层键={list(d)[:8]}'
    r = lst[0]
    if not r.get('FSRQ') or not r.get('DWJZ'):
        return False, f'字段缺失：{r}'
    return True, f'{len(lst)} 条 · 最新 {r["FSRQ"]} 净值 {r["DWJZ"]}（{r.get("JZZZL")}%）{r.get("SGZT","")}'

def codes():
    raw = body('codes')
    if raw is None:
        return False, '无响应'
    n = len(re.findall(r'"[0-9]{6}"', raw))
    if n < 1000:
        return False, f'只解析到 {n} 个基金代码，疑似被拦：{raw[:80]!r}'
    return True, f'{n} 个基金代码 · {len(raw)/1024:.0f} KB'

def hold():
    raw = body('hold')
    if raw is None:
        return False, '无响应'
    if '英伟达' in raw:
        return True, f'含英伟达持仓 · {len(raw)/1024:.1f} KB'
    m = re.search(r'content:"(.*?)",arryear', raw, re.S)
    if not m:
        return False, f'未见 content:"...",arryear 结构：{raw[:110]!r}'
    html = m.group(1)
    rows = re.findall(r'<tr>(.*?)</tr>', html, re.S)
    got = 0
    for tr in rows:
        cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', '').strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(cells) >= 5 and cells[0].isdigit():
            got += 1
    if got < 5:
        return False, f'解析出 {got} 条持仓，偏少'
    return True, f'解析出 {got} 条重仓股 · {len(raw)/1024:.1f} KB'

def fee():
    raw = body('fee')
    if raw is None:
        return False, '无响应'
    if '管理费' in raw or '托管费' in raw:
        return True, f'含费率条目 · {len(raw)/1024:.1f} KB'
    return False, f'未见费率文字：{raw[:110]!r}'

def sct():
    raw = body('sct')
    if raw is None:
        return False, '无响应'
    try:
        d = json.loads(raw)
    except Exception:
        return False, f'不是 JSON（可能被地域拦截）：{raw[:110]!r}'
    # 关键：假 key 应该换来正常的业务错误码，而不是网络层拦截
    return ('code' in d), f'业务响应 code={d.get("code")} message={str(d.get("message"))[:80]}'

checks = [
    ('080006 净值 JSON', lambda: nav('navA1')),
    ('净值 连测第2次',   lambda: nav('navA2')),
    ('净值 连测第3次',   lambda: nav('navA3')),
    ('270042 净值 JSON', lambda: nav('navB')),
    ('净值 第20页',      lambda: nav('navA20')),
    ('基金代码全表',     codes),
    ('持仓穿透页',       hold),
    ('费率页',           fee),
    ('Server酱 发送接口', sct),
]

print()
ok_n = 0
for label, fn in checks:
    try:
        ok, msg = fn()
    except Exception as e:
        ok, msg = False, f'{type(e).__name__}: {e}'
    ok_n += bool(ok)
    print(f'  {"OK  " if ok else "FAIL"} {label:<18} {msg}')
print()
print(f'  ══ 内容校验 {ok_n}/{len(checks)} 项通过 ══')
PY

echo
hr
echo "▸ 汇总"
echo
printf '%-26s %-6s %s\n' '项目' '状态' '备注'
cat "$SUMMARY"
hr
echo "探测结束"
