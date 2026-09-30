#!/usr/bin/env bash
# =============================================================================
# 专项复测：fundf10.eastmoney.com 的持仓接口 FundArchivesDatas.aspx
#
# 背景：同主机（fundf10.eastmoney.com）的费率页 jjfl_080006.html 返回 200、
#       2 秒内完成；但持仓接口 FundArchivesDatas.aspx 在境外 runner 上
#       一次 404（无 Referer）、一次 45 秒超时。要把变量一个个拆开看。
#
# 持仓穿透只服务于「平替尽调」，不是核心监控链路。
# 核心链路是 净值接口 + Server酱，两项均已验证通过。
# =============================================================================
set -uo pipefail

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
HOST=https://fundf10.eastmoney.com
OUT=/tmp/hold
mkdir -p "$OUT"

hr() { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

# 单次尝试：含两次重试，短超时（20 秒），避免一个卡住的请求吃掉整个任务
attempt() {  # attempt <序号> <显示名> <URL> <extra curl 参数...>
  local n="$1" name="$2" url="$3"; shift 3
  local body="$OUT/$n.body"
  local meta rc
  meta=$(curl -sS -L --max-redirs 5 -m 20 -o "$body" \
        -w 'HTTP %{http_code} | %{size_download} B | 共 %{time_total}s' \
        -A "$UA" "$@" "$url" 2>&1); rc=$?

  printf '  %d) %-46s ' "$n" "$name"
  if [ "$rc" -ne 0 ]; then
    printf '❌ 失败 rc=%s（%s）\n' "$rc" "$(printf '%s' "$meta" | tr -d '\n' | tail -c 60)"
    return 1
  fi
  local code="${meta#HTTP }"; code="${code%% *}"
  local size; size=$(wc -c < "$body")
  printf 'HTTP %s · %s B · %s\n' "$code" "$size" "$(printf '%s' "$meta" | sed -E 's/.*共 ([0-9.]+s)/\1/')"
  if [ "$code" = "200" ] && [ "$size" -gt 500 ]; then
    printf '        预览：'; head -c 110 "$body" | tr -d '\n'; printf '\n'
  fi
  return 0
}

J="?type=jjcc&code=080006&topline=10"
REF="-H Referer:$HOST/ccmx_080006.html"

echo "▸ 对照组：先确认这台主机本身是通的"
hr
attempt c1 "费率页（同主机，已知可用）" "$HOST/jjfl_080006.html"
attempt c2 "基金概况页" "$HOST/jbgk_080006.html"
attempt c3 "持仓页 HTML 本体" "$HOST/ccmx_080006.html"

echo
echo "▸ 变量拆解：持仓接口 FundArchivesDatas.aspx"
hr
attempt  1 "原样式：带 Referer + year=&month=" "$HOST/FundArchivesDatas.aspx$J&year=&month=&rt=0.1" $REF
attempt  2 "不带 Referer" "$HOST/FundArchivesDatas.aspx$J&year=&month=&rt=0.1"
attempt  3 "带 Referer，去掉 rt 随机数" "$HOST/FundArchivesDatas.aspx$J&year=&month=" $REF
attempt  4 "带 Referer，year 填 2026" "$HOST/FundArchivesDatas.aspx$J&year=2026&month=" $REF
attempt  5 "带 Referer，完全不带 year/month" "$HOST/FundArchivesDatas.aspx$J" $REF
attempt  6 "带 Referer，强制 HTTP/1.1" "$HOST/FundArchivesDatas.aspx$J&year=&month=&rt=0.1" $REF --http1.1
attempt  7 "带 Referer，换 type=jjcc 为 jjcc 大写 CC" "$HOST/FundArchivesDatas.aspx?type=JJCC&code=080006&topline=10&year=&month=&rt=0.1" $REF
attempt  8 "带 Referer，主机改 www 前缀" "https://www.fundf10.eastmoney.com/FundArchivesDatas.aspx$J&year=&month=&rt=0.1" $REF

echo
echo "▸ 结果判读"
hr
python3 - "$OUT" <<'PY'
import glob, os, re, sys
D = sys.argv[1]
ok = []
for p in sorted(glob.glob(os.path.join(D, '*.body')), key=lambda x: int(re.search(r'(\d+)', os.path.basename(x)).group(1))):
    raw = open(p, encoding='utf-8', errors='replace').read()
    if len(raw) < 500:
        continue
    if 'arryear' in raw or 'content:"' in raw:
        m = re.search(r'content:"(.*?)",arryear', raw, re.S)
        n = 0
        if m:
            for tr in re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S):
                cells = [re.sub(r'<[^>]+>', '', c).strip()
                         for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                if len(cells) >= 5 and cells[0].isdigit():
                    n += 1
        ok.append((os.path.basename(p), n))
print(f'  解析出持仓明细的响应文件：{len(ok)} 个')
for name, n in ok:
    print(f'    {name}: {n} 条重仓股')
PY

echo
hr
echo "专项复测结束"
