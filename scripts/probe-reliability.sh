#!/usr/bin/env bash
# =============================================================================
# 可靠性抽样：不是问「通不通」，而是问「十次里有几次通」
#
# 上一轮（run 3）暴露的现象：持仓接口同样的 URL 和参数，
#   第 1 次 200（12087 B，20 条重仓股）
#   第 2、3、4、5、7 次全部 20 秒超时
#   第 6 次（仅多一个 --http1.1）又成功
# 于是要抽样测成功率，并单独看「强制 HTTP/1.1 有没有帮助」。
#
# 同时给核心链路（净值接口）也做重复抽样 —— 它是监控的命脉，必须稳定。
# =============================================================================
set -uo pipefail

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
OUT=/tmp/rel
mkdir -p "$OUT"
: > /tmp/rel_result.txt

hr() { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

run_one() {  # run_one <编号> <URL> <是否带Referer:1/0> <附加参数...>
  local n="$1" url="$2" useref="$3"; shift 3
  local body="$OUT/$n.body"
  local size=0 code=000 rc=0

  local args=(-sS -L --max-redirs 3 -m 15 -o "$body"
              -w '%{http_code}' -A "$UA")
  [ "$useref" = "1" ] && args+=(-H "Referer:https://fundf10.eastmoney.com/ccmx_080006.html")
  args+=("$@")

  code=$(curl "${args[@]}" "$url" 2>/dev/null) || rc=$?
  [ -f "$body" ] && size=$(wc -c < "$body")

  if [ "$rc" -ne 0 ]; then
    printf '    %-6s ❌ 超时/连接失败 (rc=%s)\n' "$n" "$rc"
    printf '%s\tFAIL\trc=%s\n' "$n" "$rc" >> /tmp/rel_result.txt
    return 1
  fi
  printf '    %-6s %s · %s B\n' "$n" "HTTP $code" "$size"
  printf '%s\tOK\thttp=%s,size=%s\n' "$n" "$code" "$size" >> /tmp/rel_result.txt
  return 0
}

# -----------------------------------------------------------------------------
NAV='https://api.fund.eastmoney.com/f10/lsjz?fundCode=080006&pageIndex=1&pageSize=20'
HOLD='https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=080006&topline=10&year=&month=&rt=0.1'

echo "▸ A 组：持仓接口，默认协议，连打 4 次"
hr
for i in 1 2 3 4; do run_one "A$i" "$HOLD" 1; sleep 2; done

echo
echo "▸ B 组：持仓接口，强制 HTTP/1.1，连打 4 次"
hr
for i in 1 2 3 4; do run_one "B$i" "$HOLD" 1 --http1.1; sleep 2; done

echo
echo "▸ C 组：净值接口（核心命脉），默认协议，连打 6 次"
hr
for i in 1 2 3 4 5 6; do run_one "C$i" "$NAV" 1; sleep 1; done

echo
echo "▸ D 组：净值接口，强制 HTTP/1.1，连打 3 次"
hr
for i in 1 2 3; do run_one "D$i" "$NAV" 1 --http1.1; sleep 1; done

# -----------------------------------------------------------------------------
echo
hr
echo "▸ 成功率统计"
python3 - "$OUT" <<'PY'
import glob, os, re, sys, json
D = sys.argv[1]

def group(prefix):
    files = sorted(glob.glob(os.path.join(D, prefix + '*.body')))
    good = bad = 0
    samples = []
    for p in files:
        raw = open(p, encoding='utf-8', errors='replace').read()
        n = 0
        m = re.search(r'content:"(.*?)",arryear', raw, re.S)
        if m:
            for tr in re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S):
                cells = [re.sub(r'<[^>]+>', '', c).strip()
                         for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                if len(cells) >= 5 and cells[0].isdigit():
                    n += 1
        is_nav = raw.lstrip().startswith('{') and 'LSJZList' in raw
        if len(raw) > 3000 and (n >= 5 or is_nav):
            good += 1
            samples.append(f'{os.path.basename(p)}:{n}条' if n else f'{os.path.basename(p)}:净值OK')
        else:
            bad += 1
    total = good + bad
    if not total:
        return None
    return good, total, samples

groups = [
    ('A', '持仓接口 · 默认协议'),
    ('B', '持仓接口 · 强制HTTP/1.1'),
    ('C', '净值接口 · 默认协议'),
    ('D', '净值接口 · 强制HTTP/1.1'),
]

print()
print(f'  {"分组":<26} {"成功/总":<10} 成功率')
print('  ' + '─' * 52)
for pre, label in groups:
    r = group(pre)
    if r is None:
        continue
    good, total, samples = r
    bar = '█' * good + '░' * (total - good)
    print(f'  {label:<24} {good}/{total:<8} {good/total*100:5.0f}%  {bar}')
print()
PY

echo
hr
echo "抽样结束"
