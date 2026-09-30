#!/usr/bin/env bash
# =============================================================================
# 一键把本目录推送到 GitHub（自动识别 v2rayN / Clash 的代理端口）
#
# 用法（Git Bash）：
#   cd /e/ai/workbuddy-actions
#   bash scripts/push-to-github.sh qinglisinianchun workbuddy-actions
# 更简单：直接双击同目录下的 push-to-github.cmd
#
# 脚本会依次处理：
#   1) 初始化 git 仓库、写入提交身份（只写进本仓库 .git/config，不动全局）
#   2) ★ 网络自检：找出真正能连上 github.com 的通道
#      （之前的失败就出在这里：v2rayN 只设置了 Windows「系统代理」，
#        而 git 根本不读那个设置，于是直连 github 超时 21 秒后报
#        "Could not connect to server"。这里改成主动把系统代理读出来，
#        再逐个实测，挑第一个真能通的用。）
#   3) 远端已有历史时，把本地提交**叠加**上去（不会 non-fast-forward 被拒）
#   4) 推送前扫描暂存区，命中 token / SendKey 特征就中止
# =============================================================================
set -uo pipefail

strip_cr() { printf '%s' "${1-}" | tr -d '\r'; }

# --force-local：明知远端有本地没有的提交（比如你在 GitHub 网页上直接改过文件），
#               仍然要用本地内容覆盖它。默认不带这个参数，会先停下来问你。
FORCE_LOCAL=0
ARGS=()
for _a in ${1+"$@"}; do
  case "$_a" in
    --force-local) FORCE_LOCAL=1 ;;
    *)             ARGS+=("$_a") ;;
  esac
done
unset _a

GH_USER="$(strip_cr "${ARGS[0]-}")"
GH_REPO="$(strip_cr "${ARGS[1]-}")"
GH_EMAIL="$(strip_cr "${ARGS[2]-}")"

if [ -z "$GH_USER" ] || [ -z "$GH_REPO" ]; then
  echo "用法: bash scripts/push-to-github.sh <GitHub用户名> <仓库名> [邮箱]" >&2
  echo "示例: bash scripts/push-to-github.sh zhangsan workbuddy-actions" >&2
  echo "      bash scripts/push-to-github.sh zhangsan workbuddy-actions --force-local" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "[x] 找不到 git。请先安装 Git for Windows：https://git-scm.com/download/win" >&2
  echo "    装的时候保持默认选项（会把 git 加进系统 PATH）。" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)" || { echo "[x] 无法定位仓库目录" >&2; exit 1; }
cd "$ROOT" || { echo "[x] 无法进入目录 $ROOT" >&2; exit 1; }

EMAIL="${GH_EMAIL:-$GH_USER@users.noreply.github.com}"
REPO_URL="https://github.com/$GH_USER/$GH_REPO.git"
WEB_URL="https://github.com/$GH_USER/$GH_REPO"
NEW_URL="https://github.com/new"

echo "仓库目录：$ROOT"
echo "目标地址：$REPO_URL"
echo

# ---------------------------------------------------------------------------
# 1. 初始化 + 提交身份（git config 必须在 .git 存在之后才生效）
# ---------------------------------------------------------------------------
if [ ! -d .git ]; then
  git init -b main >/dev/null 2>&1 || git init >/dev/null 2>&1
  echo "[OK] 已初始化 git 仓库"
else
  echo "[--] 已存在 .git，跳过初始化"
fi

git config user.name  "$GH_USER"
git config user.email "$EMAIL"
echo "[OK] 提交身份（仅本仓库）= $GH_USER <$EMAIL>"

# ---------------------------------------------------------------------------
# 2. remote
# ---------------------------------------------------------------------------
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi
echo "[OK] remote origin = $REPO_URL"
echo

# ---------------------------------------------------------------------------
# 3. ★ 网络自检
#    git 只认两样东西：自己的 http.proxy 配置、以及 HTTP(S)_PROXY 环境变量。
#    它【不会】读 Windows 的「系统代理」（v2rayN / Clash 默认就只写那里），
#    所以开了 VPN 网页能打开、git 却依然超时。这里把系统代理读出来代管。
# ---------------------------------------------------------------------------
PROBE_REPO="https://github.com/octocat/Hello-World.git"   # 必定存在的公开小仓库，只用来测连通性

have_timeout=0
command -v timeout >/dev/null 2>&1 && have_timeout=1

port_open() {  # 快速的本地端口探测，端口没开就不必浪费时间等超时
  (exec 3<>"/dev/tcp/$1/$2") >/dev/null 2>&1
}

probe() {  # probe <超时秒> [代理URL]；不给代理 = 直连
  local tmo="$1" proxy="${2-}"
  local g=(git -c credential.helper=)
  [ -n "$proxy" ] && g+=(-c "http.https://github.com/.proxy=$proxy")
  g+=(ls-remote --heads "$PROBE_REPO")

  if [ -n "$proxy" ]; then
    if [ "$have_timeout" = "1" ]; then
      GIT_TERMINAL_PROMPT=0 timeout "$tmo" "${g[@]}" >/dev/null 2>&1
    else
      GIT_TERMINAL_PROMPT=0 "${g[@]}" >/dev/null 2>&1
    fi
  else
    # 直连测试时必须把环境变量里的代理摘掉，否则测的还是代理
    if [ "$have_timeout" = "1" ]; then
      ( unset HTTPS_PROXY https_proxy HTTP_PROXY http_proxy ALL_PROXY all_proxy
        GIT_TERMINAL_PROMPT=0 timeout "$tmo" "${g[@]}" ) >/dev/null 2>&1
    else
      ( unset HTTPS_PROXY https_proxy HTTP_PROXY http_proxy ALL_PROXY all_proxy
        GIT_TERMINAL_PROMPT=0 "${g[@]}" ) >/dev/null 2>&1
    fi
  fi
}

CANDS=()
add_cand() {
  local v; v="$(strip_cr "${1-}")"
  [ -z "$v" ] && return 0
  local c
  for c in ${CANDS[@]+"${CANDS[@]}"}; do
    [ "$c" = "$v" ] && return 0
  done
  CANDS+=("$v")
}

# (1) 环境变量里已经设了代理的 —— 优先级最高
for v in "${HTTPS_PROXY-}" "${https_proxy-}" "${HTTP_PROXY-}" "${http_proxy-}" "${ALL_PROXY-}" "${all_proxy-}"; do
  add_cand "$v"
done

# (2) Windows 系统代理（v2rayN / Clash 的「系统代理」模式写在这里）
REG="/c/Windows/System32/reg.exe"
command -v reg >/dev/null 2>&1 && REG="reg"
if [ -x "$REG" ] || command -v "$REG" >/dev/null 2>&1; then
  IES='HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  pen="$("$REG" query "$IES" -v ProxyEnable 2>/dev/null | tr -d '\r' | grep -o '0x[0-9a-fA-F]*' | tail -1)"
  psv="$("$REG" query "$IES" -v ProxyServer 2>/dev/null | tr -d '\r' | awk '/ProxyServer/{print $NF}' | tail -1)"
  if [ "$pen" = "0x1" ] && [ -n "$psv" ]; then
    case "$psv" in
      *=*)  # 形如 "http=127.0.0.1:10809;https=127.0.0.1:10809"
        https_part="$(printf '%s' "$psv" | tr ';' '\n' | sed -n 's/^https=//p' | head -1)"
        http_part="$(printf '%s' "$psv" | tr ';' '\n' | sed -n 's/^http=//p' | head -1)"
        psv="${https_part:-${http_part:-}}"
        ;;
    esac
    if [ -n "$psv" ]; then
      case "$psv" in
        *"://"*) add_cand "$psv" ;;
        *)       add_cand "http://$psv" ;;
      esac
    fi
  fi
fi

# (3) 直连（VPN 开的是 TUN / 全局模式时走这条）
add_cand "__DIRECT__"

# (4) 常见本地代理端口兜底
for pp in "10809 http" "10808 socks5h" "7897 http" "7890 http" "1080 http" \
          "7891 socks5h" "2080 http" "4780 http" "8889 http" "20171 http" "33210 http"; do
  add_cand "${pp##* }://127.0.0.1:${pp%% *}"
done

echo "▶ 网络自检：正在找能连上 github.com 的通道…"
CHOSEN=""
CHOSEN_DESC=""
FOUND=0

for c in ${CANDS[@]+"${CANDS[@]}"}; do
  if [ "$c" = "__DIRECT__" ]; then
    printf '   · 直连 github.com … '
    if probe 10; then CHOSEN=""; CHOSEN_DESC="直连（无需代理）"; echo "可用"; FOUND=1; break; else echo "不通"; fi
  else
    hp="${c#*://}"; host="${hp%%:*}"; port="${hp##*:}"
    printf '   · %s … ' "$c"
    if [ "$host" = "127.0.0.1" ] || [ "$host" = "localhost" ]; then
      if ! port_open "$host" "$port"; then echo "端口未监听，跳过"; continue; fi
    fi
    if probe 18 "$c"; then CHOSEN="$c"; CHOSEN_DESC="$c"; echo "可用"; FOUND=1; break; else echo "不通"; fi
  fi
done

if [ "$FOUND" != "1" ]; then
  echo
  echo "[x] 所有已知通道都连不上 github.com。逐条确认："
  echo "    1) 你的代理客户端（截图里是 v2rayN）正在运行，且打开了「系统代理」或「TUN 模式」"
  echo "    2) 用浏览器能打开 https://github.com —— 打不开就是代理没生效"
  echo "    3) 知道代理端口的话，手动指定后重跑："
  echo "         HTTPS_PROXY=http://127.0.0.1:端口 bash scripts/push-to-github.sh $GH_USER $GH_REPO"
  exit 1
fi

echo "[OK] 使用通道：$CHOSEN_DESC"
if [ -n "$CHOSEN" ]; then
  git config --local "http.https://github.com/.proxy" "$CHOSEN"
  echo "     已写入本仓库 .git/config（只影响这个仓库，不动全局设置）"
else
  git config --local --unset "http.https://github.com/.proxy" >/dev/null 2>&1 || true
fi
echo

# ---------------------------------------------------------------------------
# 4. ★ 先确保已登录 GitHub（这一步会弹浏览器，只有第一次要做）
#    为什么要单独拆出来：登录失败时 git 会拿「空凭据」去请求，
#    GitHub 对空凭据同样回 404 Repository not found —— 会被误判成
#    「仓库被删了」。先把登录做成一个有明确成功/失败反馈的步骤，
#    后面读到的 "not found" 才是可信的。
# ---------------------------------------------------------------------------
has_cred() {  # 只看系统里已存的凭据，绝不弹窗
  printf 'protocol=https\nhost=github.com\n\n' \
    | GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never \
      git -c credential.interactive=false credential fill 2>/dev/null \
    | grep -q '^password=.'
}

echo "▶ 检查 GitHub 登录状态…"
if has_cred; then
  echo "[OK] 已有 GitHub 凭据（在 Windows 凭据管理器里），不用重新登录"
else
  echo
  echo "  ⚠  还没有登录过 GitHub，下面这一步必须做一次："
  echo
  echo "     1) 按回车后，会弹出一个浏览器页面（github.com）"
  echo "     2) 用你的 GitHub 账号登录"
  echo "     3) 看到「Authorize Git Credential Manager」页面，点【绿色的 Authorize】按钮"
  echo "     4) 浏览器提示 Authorization succeeded 就可以关掉了"
  echo
  echo "     浏览器窗口不会自己跳回来，点完按钮才知道成没成。最多等 5 分钟。"
  echo "     如果浏览器没弹出来 / 打不开网页 → 说明 VPN 没生效，先确认能上 github.com"
  echo
  printf "     准备好了按【回车】开始授权…"
  read -r _dummy 2>/dev/null || true
  echo
  echo "▶ 正在等待浏览器授权…"
  AUTH_LOG="${TMPDIR:-/tmp}/gh-auth.$$.log"
  if [ "$have_timeout" = "1" ]; then
    timeout 300 git ls-remote origin >"$AUTH_LOG" 2>&1
  else
    git ls-remote origin >"$AUTH_LOG" 2>&1
  fi

  if has_cred; then
    echo "[OK] 授权成功，凭据已保存到 Windows 凭据管理器（以后不用再登录）"
  else
    echo
    echo "[x] 没有拿到 GitHub 凭据 —— 这次授权没完成。"
    echo "    git 的原话："
    sed 's/^/        /' "$AUTH_LOG" 2>/dev/null | tail -12
    echo
    echo "    逐条对一下："
    echo "      ① 浏览器窗口弹出来了吗？被关掉、或没点绿色 Authorize 按钮 → 重跑一次重来"
    echo "      ② 浏览器能打开 github.com 吗？打不开 = VPN 没生效（脚本已经帮你给 git 配好代理了，"
    echo "         但浏览器仍然走你自己的 v2rayN，必须保持开着）"
    echo "      ③ 手动兜底：浏览器打开 https://github.com/login/device ，按提示输一次码"
    echo "      ④ 都试过还不行，就用令牌方式（见 README「登录不上怎么办」）"
    exit 1
  fi
fi
echo

# ---------------------------------------------------------------------------
# 5. 读远端历史 —— 到这里凭据一定是有效的，所以 "not found" 才可信
# ---------------------------------------------------------------------------
echo "▶ 读取远端仓库状态…"
FETCH_OUT="$( { if [ "$have_timeout" = "1" ]; then timeout 300 git fetch origin 2>&1; else git fetch origin 2>&1; fi; } )"
FETCH_RC=$?

if [ $FETCH_RC -eq 0 ] && git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null; then
  # 远端有你本地没有的提交 —— 最常见的原因：你直接在 GitHub 网页上改了文件
  # （比如改 .github/workflows/daily.yml 里的定时时间）。
  # 这一步继续下去会用本地内容覆盖那些文件，网页上的改动会**静默消失**，
  # 所以默认先停下来说清楚，要覆盖必须显式加 --force-local。
  REMOTE_AHEAD="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  if [ "$REMOTE_AHEAD" != "0" ] && [ "$FORCE_LOCAL" != "1" ]; then
    echo
    echo "[!] 远端有 $REMOTE_AHEAD 个你本地没有的提交 —— 多半是你直接在 GitHub 网页上改过文件。"
    echo
    echo "    这些提交是："
    git log --oneline HEAD..origin/main | sed 's/^/      /'
    echo
    echo "    涉及的文件（继续推的话，本地版本会覆盖它们）："
    git diff --name-only HEAD origin/main | sed 's/^/      /'
    echo
    echo "    选一条："
    echo "      A) 想保留网页上的改动 → 先在本地同步，再重跑本脚本"
    echo "           git fetch origin && git reset --hard origin/main"
    echo "      B) 确认要用本地覆盖远端 → 加参数重跑"
    echo "           bash scripts/push-to-github.sh $GH_USER $GH_REPO --force-local"
    echo
    exit 1
  fi
  echo "[OK] 远端 main 已有历史，本地提交将叠加在其之上（不会覆盖你的仓库历史）"
  git reset --mixed origin/main >/dev/null
elif [ $FETCH_RC -eq 124 ]; then
  echo "[x] 取远端历史超时（网络太慢或代理不稳定）。稍等一下重跑一次即可。"
  exit 1
elif printf '%s' "$FETCH_OUT" | grep -qiE 'repository not found|does not exist'; then
  echo
  echo "[x] 仓库确实不在了 —— $GH_USER/$GH_REPO"
  echo "    （登录是成功的，所以这次不是误判）"
  echo
  echo "    只能在网页上重建（30 秒）："
  echo "      1) 打开        $NEW_URL"
  echo "      2) Repository name 填： $GH_REPO"
  echo "      3) 选 Private"
  echo "      4) 下面三个勾（Add a README / .gitignore / license）**一个都别勾**"
  echo "      5) 点 Create repository"
  echo "      6) 回到这里，双击 push-to-github.cmd 再来一次（这次不用再登录了）"
  echo
  echo "    ⚠ 仓库被删过 → 那 5 个 Secret 也一起没了，建好仓库后要重新加："
  echo "      WB_TOKEN / WB_USER_ID / WB_DOMAIN / SERVERCHAN_KEY / FEISHU_WEBHOOK"
  echo "      （位置：仓库 Settings → Secrets and variables → Actions → New repository secret）"
  echo
  echo "    git 的原话："
  printf '%s\n' "$FETCH_OUT" | sed 's/^/        /' | tail -8
  exit 1
elif printf '%s' "$FETCH_OUT" | grep -qiE 'authentication failed|could not read Username|invalid username|403 Forbidden|unable to get password'; then
  echo
  echo "[x] GitHub 登录状态失效了（凭据过期或被撤销）。重跑一次重新授权即可。"
  echo "    git 的原话："
  printf '%s\n' "$FETCH_OUT" | sed 's/^/        /' | tail -8
  exit 1
elif [ $FETCH_RC -ne 0 ]; then
  echo
  echo "[x] 读取远端失败（非上述已知原因）。git 的原话："
  printf '%s\n' "$FETCH_OUT" | sed 's/^/        /' | tail -12
  exit 1
else
  echo "[--] 远端是空的（刚建好的仓库），按首次推送处理"
fi

# ---------------------------------------------------------------------------
# 6. 暂存 + 安全扫描
# ---------------------------------------------------------------------------
git add -A

STAGED="$(git diff --cached --name-only)"
if [ -z "$STAGED" ]; then
  echo "[--] 没有需要提交的变更"
else
  echo "▶ 待提交文件："
  printf '%s\n' "$STAGED" | sed 's/^/     /'

  LEAK="$(printf '%s\0' "$STAGED" | xargs -0 -r grep -lE \
      'SCT[A-Za-z0-9]{28,}|github_pat_[A-Za-z0-9_]{30,}|ghp_[A-Za-z0-9]{30,}|eyJhbGciOi[A-Za-z0-9._-]{200,}' \
      2>/dev/null || true)"
  if [ -n "$LEAK" ]; then
    echo
    echo "[x] 中止：暂存区里有文件疑似包含凭据/token 特征："
    printf '%s\n' "$LEAK" | sed 's/^/     /'
    echo "    请把它们移出本目录或加进 .gitignore，然后重跑。已执行 git reset 取消暂存。"
    git reset >/dev/null
    exit 1
  fi
  echo "[OK] 凭据扫描通过"

  # 提交信息可用 PUSH_COMMIT_MSG 覆盖；不设置时用这条中性文案。
  # （原版脚本把「Buddy 加油站」写死在这里，复制到别的项目会留下错误的历史。）
  if git commit -m "${PUSH_COMMIT_MSG:-chore: 同步本地改动（自动提交）}" >/dev/null; then
    echo "[OK] 已提交"
  fi
fi

git branch -M main >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 7. 推送
# ---------------------------------------------------------------------------
echo
echo "▶ 开始推送…（第一次会弹出浏览器让你登录 GitHub，登录后点绿色 Authorize 按钮）"
echo

PUSH_LOG="${TMPDIR:-/tmp}/push-to-github.$$.log"
if [ "$have_timeout" = "1" ]; then
  timeout 300 git push -u origin main 2>&1 | tee "$PUSH_LOG"
else
  git push -u origin main 2>&1 | tee "$PUSH_LOG"
fi
PUSH_RC="${PIPESTATUS[0]}"

if [ "$PUSH_RC" -eq 0 ]; then
  echo
  echo "[OK] 推送完成：$WEB_URL"
  echo
  echo "想立刻验证：$WEB_URL/actions → 选对应工作流 → Run workflow"
  rm -f "$PUSH_LOG" 2>/dev/null || true
  exit 0
fi

echo
if [ "$PUSH_RC" -eq 124 ]; then
  echo "[x] 推送超时。多半是代理节点慢，换个节点或过一会儿重跑一次即可。"
elif grep -qiE 'repository not found|not found' "$PUSH_LOG" 2>/dev/null; then
  echo "[x] GitHub 说仓库不存在 —— 到 $NEW_URL 建一个同名 Private 空仓库，再重跑。"
elif grep -qiE 'non-fast-forward|fetch first|rejected' "$PUSH_LOG" 2>/dev/null; then
  echo "[x] 远端有本地没有的提交。重跑一次即可（脚本第 4 步会先取回远端历史再叠加）。"
  echo "    若反复失败：git push -u origin main --force （会用本地覆盖远端历史，谨慎）"
elif grep -qiE 'authentication failed|could not read Username|403' "$PUSH_LOG" 2>/dev/null; then
  echo "[x] 登录 GitHub 失败。清掉旧凭据后重跑："
  echo "      printf 'protocol=https\\nhost=github.com\\n\\n' | git credential reject"
else
  echo "[x] 推送失败。排查顺序："
  echo "    1) 地址拼错？确认这里能打开：$WEB_URL"
  echo "    2) 代理不稳定？换个节点，或重跑一次"
  echo "    3) 上面打印的具体报错是最终依据"
fi
echo
echo "完整日志：$PUSH_LOG"
exit 1
