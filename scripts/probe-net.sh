#!/usr/bin/env bash
# =============================================================================
# 探测：GitHub Actions 的 runner 能不能访问「纳指平替漂移监控」所需的全部外部接口
#
# 这是把监控搬上 GitHub 之前必须过的一关。本机（走 VPN）能访问，
# 不代表 GitHub 的机器（多在境外）也能访问。达不成就白搭。
#
# 只探测、不产生副作用（Server酱 那项不带 key，不会真的发出推送）。
# =============================================================================
set -uo pipefail

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
BODIES=/tmp/probe_bodies
SUMMARY=/tmp/probe_summary.txt
mkdir -p "$BODIES"
: > "$SUMMARY"

hr() { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

record() {  # record <名称> <状态> <说明>
  printf '%-30s %-6s %s\n' "$1" "$2" "$3" >> "$SUMMARY"
}

# probe <存档名> <显示名> <URL> [Referer]
probe() {
  local slug="$1" name="$2" url="$3" ref="${4-}"
  local out="$BODIES/$slug.body"
  local hdr=(-A "$UA")
  [ -n "$ref" ] && hdr+=(-H "Referer: $ref")

  hr
  printf '▸ %s\n  %s\n' "$name" "$url"

  local meta rc
  meta=$(curl -sS -m 45 -o "$out" \
        -w 'HTTP %{http_code} | %{size_download} B | DNS %{time_namelookup}s | TLS %{time_appconnect}s | 共 %{time_total}s' \
        "${hdr[@]}" "$url" 2>&1); rc=$?
  printf '  %s\n' "$meta"

  if [ "$rc" -ne 0 ]; then
    printf '  ❌ curl 退出码 %s —— 连接层就失败了\n' "$rc"
    record "$name" "FAIL" "curl rc=$rc"
    return 1
  fi

  local code="${meta#HTTP }"; code="${code%% *}"
  printf '  ── 响应前 180 字节 ──\n  '
  head -c 180 "$out" 2>/dev/null | tr -d '\n'
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
echo "  curl   : $(curl --version | head -1)"
ipinfo=$(curl -sS -m 25 https://ipinfo.io/json 2>/dev/null || true)
if [ -n "$ipinfo" ]; then
  echo "  出口 IP: $(printf '%s' "$ipinfo" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("ip"),"|",d.get("city"),d.get("region"),d.get("country"),"|",d.get("org"))' 2>/dev/null || echo 解析失败)"
else
  echo "  出口 IP: 取不到"
fi
echo

# -----------------------------------------------------------------------------
echo "【1】东方财富 · 历史净值接口 —— 监控的命脉"
probe navA "净值 080006" \
  "https://api.fund.eastmoney.com/f10/lsjz?fundCode=080006&pageIndex=1&pageSize=20" \
  "https://fundf10.eastmoney.com/jjjz_080006.html"
probe navB "净值 270042" \
  "https://api.fund.eastmoney.com/f10/lsjz?fundCode=270042&pageIndex=1&pageSize=20" \
  "https://fundf10.eastmoney.com/jjjz_270042.html"

# -----------------------------------------------------------------------------
echo "【2】基金代码全表（注意是 http 明文，测会不会被拦非加密请求）"
probe codes "基金代码表" "http://fund.eastmoney.com/js/fundcode_search.js"

# -----------------------------------------------------------------------------
echo "【3】持仓穿透与费率页（平替尽调工具用）"
probe hold "持仓 080006" \
  "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=080006&topline=10&year=&month=&rt=0.1"
probe fee "费率 080006" "https://fundf10.eastmoney.com/jjfl_080006.html"

# -----------------------------------------------------------------------------
echo "【4】微信推送通道 Server酱（不带 key，只测网络能不能到）"
probe sct "Server酱主机" "https://sctapi.ftqq.com/"

# -----------------------------------------------------------------------------
echo "【5】对照组（证明 runner 本身有正常外网）"
probe gh "对照组 github" "https://api.github.com"
probe gg "对照组 google" "https://www.google.com"

# -----------------------------------------------------------------------------
echo
hr
echo "▸ 内容校验 —— 200 也可能是被拦后返回的空壳页，必须验真数据"
python3 - "$BODIES" <<'PY'
import json, os, re, sys, glob
B = sys.argv[1]
def body(slug):
    p = os.path.join(B, slug + '.body')
    if not os.path.exists(p):
        return None
    return open(p, encoding='utf-8', errors='replace').read()

def one_nav(slug, label):
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
    return True, f'{len(lst)} 条 · 最新 {r["FSRQ"]} 净值 {r["DWJZ"]}（{r.get("JZZZL")}%）'

def codes():
    raw = body('codes')
    if raw is None:
        return False, '无响应'
    n = len(re.findall(r'"[0-9]{6}"', raw))
    if n < 1000:
        return False, f'只解析到 {n} 个基金代码，疑似被拦'
    return True, f'{n} 个基金代码 · {len(raw)/1024:.0f} KB'

def hold():
    raw = body('hold')
    if raw is None:
        return False, '无响应'
    if '英伟达' in raw or 'NVDA' in raw:
        return True, f'含英伟达持仓 · {len(raw)/1024:.1f} KB'
    names = re.findall(r'gpdm="(\d{6})"', raw) or re.findall(r'\["([^"]{2,8})",\d', raw)
    if len(names) >= 5:
        return True, f'检出 {len(names)} 条持仓 · {len(raw)/1024:.1f} KB'
    return False, f'{len(raw)/1024:.1f} KB，未见预期持仓结构：{raw[:120]!r}'

def fee():
    raw = body('fee')
    if raw is None:
        return False, '无响应'
    if '管理费' in raw or '托管费' in raw:
        return True, f'含费率条目 · {len(raw)/1024:.1f} KB'
    return False, f'{len(raw)/1024:.1f} KB，未见费率文字：{raw[:120]!r}'

def sct():
    raw = body('sct')
    if raw is None:
        return False, '无响应'
    # 主机能通即可：会返回 JSON 错误（缺 key），这正说明服务是活的
    return ('msg' in raw or 'code' in raw or '{' in raw[:50]), f'响应 {len(raw)} B：{raw[:90]!r}'

checks = [
    ('080006 净值 JSON', lambda: one_nav('navA', 'A')),
    ('270042 净值 JSON', lambda: one_nav('navB', 'B')),
    ('基金代码全表',     codes),
    ('持仓穿透页',       hold),
    ('费率页',           fee),
    ('Server酱 主机',    sct),
]

print()
ok_n = 0
for label, fn in checks:
    try:
        ok, msg = fn()
    except Exception as e:
        ok, msg = False, f'{type(e).__name__}: {e}'
    ok_n += ok
    print(f'  {"✅" if ok else "❌"} {label:<20} {msg}')
print()
print(f'  ══ 内容校验 {ok_n}/{len(checks)} 项通过 ══')
PY

echo
hr
echo "▸ 汇总"
echo
printf '%-30s %-6s %s\n' '项目' '状态' '备注'
cat "$SUMMARY"
hr
echo "探测结束"
