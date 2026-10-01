# tools/ —— 仓库运维工具

`github.com` 被代理挡住、只有 `api.github.com` 能通时，**`git push` 必死，但仓库运维照样能做**。
这两个脚本就是为此存在的：全部走 GitHub REST API，不依赖 git 传输通道。

---

## 令牌从哪来

两个脚本都**不需要手动填令牌**：

1. 先读环境变量 `GITHUB_TOKEN`；
2. 没设就从 **Windows 凭据管理器**里取（`git credential fill`）—— 也就是 `git push` 用过的那份，
   权限实测为 `gist, repo, workflow`，**含 `repo`，所以能写 Actions Secrets**。

取凭据时脚本强制 `GIT_TERMINAL_PROMPT=0` + `GCM_INTERACTIVE=never` + `credential.interactive=false`，
**只读不弹窗**：没有凭据就快速失败，不会卡在那儿等输入。

> 换到 macOS / Linux 时，把 `get_token()` 里的凭据读取换成对应平台的
> `git credential fill`（macOS 走 osxkeychain，Linux 走 libsecret），其余逻辑不用动。

---

## gh.py —— 日常运维

```bash
PY=python3     # Windows 上换成 python

python tools/gh.py show   qinglisinianchun/fund-drift-monitor
python tools/gh.py runs   qinglisinianchun/fund-drift-monitor 5
python tools/gh.py jobs   qinglisinianchun/fund-drift-monitor <run_id>
python tools/gh.py log    qinglisinianchun/fund-drift-monitor <job_id>
python tools/gh.py run    qinglisinianchun/fund-drift-monitor daily.yml
python tools/gh.py secret qinglisinianchun/fund-drift-monitor SERVERCHAN_KEY SCTxxxx
python tools/gh.py public qinglisinianchun/fund-drift-monitor
python tools/gh.py pages  qinglisinianchun/fund-drift-monitor main /
```

| 子命令 | 干什么 | 什么时候用 |
|---|---|---|
| `show` | 一眼看全：可见性 / Pages 状态 / Secrets 列表 / 各 workflow 是否 active | **排障第一步**，先看它 |
| `runs` | 列最近 N 次运行（含 conclusion 与 head_sha） | 想知道「定时任务到底跑了没」 |
| `jobs` | 列某次运行下的 job 与每个 step 的结果 | 定位是哪个步骤挂了 |
| `log` | 打印某个 job 的**纯文本日志**，可直接 grep | 抓真实报错 |
| `logrun` | 按 run_id 把该次运行所有 job 的日志全打出来 | 一把梭 |
| `run` | 手动触发 workflow_dispatch | 不想等定时，立刻跑一次 |
| `secret` | 写 Actions Secret（libsodium sealed box 加密） | 换推送通道 / 换 key |
| `public` | 把仓库改成公开 | 已公开，一般不用 |
| `pages` | 开启或更新 GitHub Pages | 已开启，一般不用 |

**`secret` 子命令需要 PyNaCl**（`import nacl`）。没有就 `pip install pynacl`。

---

## reupload-history.py —— 改写历史后重传

```bash
python tools/reupload-history.py qinglisinianchun/fund-drift-monitor main --dry-run   # 先干跑
python tools/reupload-history.py qinglisinianchun/fund-drift-monitor main
```

**用途**：当本地提交历史被改写（本项目是为了把公开前的 QQ 邮箱换成 noreply 地址），
而 `github.com` 又不通、没法 `git push --force` 时，用 Git Data API 重建提交链并强推。

**为什么只重建 commit、不重传文件**：改写只动了 commit 的 author/committer，
**tree 与 blob 一个字节都没变**，SHA 和远端已有对象完全相同 —— 所以只要重建 commit 对象即可。
一个 commit 一次 API 调用，很轻。

**安全设计**：更新分支指针前会二次读取远端 HEAD，如果和我们开始时读到的不一致
（说明这期间有人推了新提交），直接中止，不覆盖别人的东西。

---

## 踩过的坑（脚本里都已经绕过，改脚本时别踩回去）

| 坑 | 现象 | 处理 |
|---|---|---|
| `api.github.com` 不带 `User-Agent` | **一律 403** | 所有请求都带 UA。这**不是被墙**，别误判 |
| 日志接口 302 跳转 | 跳到带签名的 Azure Blob 地址，带着 `Authorization` 去访问那个地址会被拒（401 InvalidAuthenticationInfo） | `gh.py` 里用 `_NoRedirect` 禁用自动跳转，手动拿 `Location` 再**裸访问** |
| Windows 命令行参数不能含 NUL | `git log --format=` 里用 `%x00` 作分隔符会炸 | 改用 ASCII 的 `%x1e` / `%x1f` |
| Git Bash 会转换参数里的 `/` | 路径被转成 Windows 路径 | 需要时加 `MSYS_NO_PATHCONV=1` |
| 日志接口有延迟 | 运行刚结束就抓日志可能拿到空内容 | 等几十秒再抓 |

---

## 已知的通道故障模式

`github.com` 和 `api.github.com` 是**两条不同的通道**，代理白名单经常只挡前者。
2026-09-30 实测：同一次会话里 `github.com` 先能通、几十分钟后就被
`502 CONNECT tunnel failed`，而 `api.github.com` 一直 200 —— 所以本套工具是刚需，不是备胎。
