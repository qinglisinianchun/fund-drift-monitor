# 部署到 GitHub 说明 · 纳指平替漂移监控

> 最后更新：2026-10-01
>
> **本文件是这个项目的运维入口。** 换电脑、换人接手、或者隔半年回来看，从这一份读起就够。
> 项目策略与阈值原理见 [`说明.md`](说明.md)，仓库总览见 [`README.md`](README.md)。

---

## 一、这是什么，现在跑在哪

盯住 **080006 长盛环球行业混合(QDII)A** 还是不是 **270042 广发纳斯达克100ETF联接(QDII)A** 的合格平替。
主动基金有权换仓，一旦它不再复制纳指，净值走势会露出马脚 —— 脚本就在盯这个偏差，脱钩就推微信。

整套东西跑在 **GitHub 的服务器上**，跟你自己的电脑开不开机**完全无关**。

| 项 | 值 |
|---|---|
| 仓库 | <https://github.com/qinglisinianchun/fund-drift-monitor> |
| 可见性 | **公开** |
| 看板 | <https://qinglisinianchun.github.io/fund-drift-monitor/> |
| 每日巡检 | 北京时间每天 **03:07、07:07**（UTC 19:07、23:07） |
| 每周周报 | 北京时间 **周日 09:07**（UTC 周日 01:07） |
| 推送 | Server酱 → 微信，key 在 **Actions Secrets → `SERVERCHAN_KEY`** |
| 运行依赖 | Python 3 标准库，**零第三方包** |
| 数据源 | 东方财富历史净值接口 |

**本机（办公室电脑）的本地副本已按你的要求清理干净。**
所有需要保留的东西都在这个仓库里 —— 以后要改，从仓库拉一份下来就行，见第四节。

---

## 二、仓库文件地图

```
【运行主链】—— 每天自动跑的就是这几个
monitor.py            巡检：拉净值 → 合并缓存 → 算滚动偏差 → 判触发 → 出 数据/latest.json
notify.py             推送：alert 模式（有触发才推）/ weekly 模式（每周汇总）
生成看板.py             把 数据/latest.json 渲染成单文件 index.html
run.py                本地一键跑三步（Windows）
run.sh                同上，Linux 入口（Actions 里用的就是它）
weekly.sh             每周周报入口
index.html            看板页面（GitHub Pages 首页，由脚本生成，别手改）
crontab.txt           云电脑 cron 模板（现在用 Actions，不需要它，留作备用）

【自动运行】
.github/workflows/daily.yml     每日巡检：巡检 → 推送 → 刷看板 → 提交数据回仓库
.github/workflows/weekly.yml    每周周报：同上，但无论是否漂移都推

【数据】—— 由 Actions 自动提交回来，这是补跑连续性的依据
数据/nav_080006.json    被监控基金的净值缓存
数据/nav_270042.json    基准基金的净值缓存
数据/latest.json        最新巡检状态（看板的数据源）
数据/last_run.txt       上次运行日 —— 别删，补跑靠它
数据/notify_config.json 推送通道配置（**密钥一律留空**，真值走 Secrets）
数据/trigger.json       仅在触发时生成，触发解除后自动删，已 gitignore

【文档】
部署到GitHub说明.md      本文件 —— 运维入口
说明.md                  策略详解：为什么监控、为什么 2026-07-01 起、阈值怎么定的
README.md                仓库门面：项目简介 + 判断逻辑 + 目录说明
docs/云电脑部署说明.md    历史方案（豆包云电脑 + crontab），已被 Actions 取代，仅作参考
分析/尽调结论_016701.md   当初为什么选 080006 顶替 270042 的尽调结论

【工具】—— 本地运维用，不参与日常运行
tools/README.md              工具用法与踩过的坑
tools/gh.py                  仓库运维：看状态 / 写 secret / 触发 workflow / 抓日志
tools/reupload-history.py    改写提交历史后用 API 强推

【脚本】
分析/平替尽调.py          评估任意基金能否作纳指平替
分析/持仓穿透.py          抓基金前十大持仓
分析/费率抓取.py          抓管理费 / 托管费 / 申购费
测试/测试推送.py          推送通道联通测试（换 key 后先跑它）
测试/测试看板悬停.py       看板交互自动化测试（本机 Edge CDP）

【留档】
probe/                  搬迁前「GitHub 上到底跑不跑得通」的实测留档，不参与日常运行
probe/探测结论.md        结论 + 四个坑的完整复现步骤 ← 想知道为什么这么写代码，看这个
probe/probe-net.yml.archived  探测用工作流，**已移出 .github/workflows/** 所以不会被当活跃工作流跑
```

---

## 三、你只在三件事上需要动手

### 1. 想立刻看结果 → 手动触发一次
仓库页 → **Actions** → 左边选 `每日巡检` → 右边 **Run workflow**。
一两分钟后看板上就有新数据。

### 2. 想换推送通道 / 换密钥
仓库页 → **Settings** → **Secrets and variables** → **Actions** → 改 `SERVERCHAN_KEY`。
支持三个通道，改 `数据/notify_config.json` 里的 `channel` 字段即可：

| channel 值 | 需要的 Secret |
|---|---|
| `serverchan`（当前） | `SERVERCHAN_KEY` |
| `wecom_webhook` | `WECOM_WEBHOOK_URL` |
| `pushplus` | `PUSHPLUS_TOKEN` |

### 3. 想停掉推送
把 `数据/notify_config.json` 的 `channel` 改成 `"none"` —— 只记日志、不推微信，监控本身照常跑。

---

## 四、以后要改动，怎么上手

本机副本已清理，**从仓库拉一份到任意机器即可**，脚本路径无关（用 `os.path.dirname(__file__)` 定位自身目录）。

```bash
git clone https://github.com/qinglisinianchun/fund-drift-monitor.git
cd fund-drift-monitor
python run.py          # Windows 直接跑，验证环境
bash run.sh            # Linux / macOS
```

改完推回去。**如果 `git push` 因为代理超时失败，走 API 通道**（`tools/gh.py` 那套），
或者直接把改动贴到 GitHub 网页版编辑器里 —— 内容不多时这条路最快。

**本地跑要推微信**：把 key 写进 `数据/notify_config.json`，或临时 `export SERVERCHAN_KEY=xxx`。
**推之前务必确认 `数据/notify_config.json` 里是空 key** —— 它进公开仓库。

### 改参数改哪

| 想改什么 | 改哪 |
|---|---|
| 监控对象 / 基准基金 | `monitor.py` 顶部 `FUND_A` / `FUND_B` |
| 四窗口阈值与连续确认天数 | `monitor.py` 的 `WINDOWS` |
| 红灯线 | `monitor.py` 的 `ALERT` |
| 有效比较起点 | `monitor.py` 的 `VALID_FROM`（现为 `2026-07-01`，理由见 `说明.md`） |
| 净值缓存保留天数 | `monitor.py` 的 `KEEP`（现为 260） |
| 巡检时间 | `.github/workflows/daily.yml` 的 cron（**改完注意是 UTC**） |
| 看板样式 | `生成看板.py` |

---

## 五、为什么这么设计（三个关键决定，别轻易推翻）

### ① 密钥不能只放 Secrets
`数据/notify_config.json` 本身也会进公开库，里面的明文 key 照样全世界可见。
所以做了两层：

- 仓库里的 `notify_config.json` **密钥一律留空**（只留通道名），真值只在 Secrets 里；
- `notify.py` 的 `load_cfg()` 把**环境变量叠加到 JSON 配置上**（不是替换），
  所以本地把 key 写进 JSON 照样能跑，云端只认 Secrets。

再加一道兜底：每次运行都会扫一遍代码里有没有形如 `SCT` + 长串字符的明文 key，
扫到就直接让这次运行失败，防止哪天手滑提交上去。

> 首跑时这道自检误报过一次 —— `probe/scripts/probe-net.sh` 里为验证接口连通性
> 故意写了个假 key（`SCT000000thisIsAFakeKeyForProbe`）。已修正为：排除 `probe/` 目录
> + 忽略含 fake / example / placeholder 字样的占位串。

### ② 一天跑两次 + 把数据提交回仓库
GitHub 官方说明定时任务在负载高峰**可能延迟、甚至偶发不执行**。两条对策：

- **跑两次**（03:07 / 07:07）互为兜底；
- **每次跑完把 `数据/` 和 `index.html` 提交回仓库**。

第二条是关键。`last_run.txt` 和净值缓存留在仓库里，下次运行才知道「上次跑到哪」，
中间落下的交易日会被自动补上（补跑情况会标在推送正文里）。
顺带还解决了另一个问题：仓库天天有提交，**永远不会触发「60 天不活动」被冻结**。

时间都用 `:07` 而不是 `:00`，也是为了避开整点高峰。

### ③ 看板从 `看板.html` 改名为 `index.html`
GitHub Pages 的站点首页必须是 `index.html`，所以改了 `生成看板.py` 的输出名。
另外**免费版 Pages 只支持公开仓库** —— 这和「私有仓库不受 60 天限制」是两条互不相干的规则。

---

## 六、隐私处理（2026-09-30）

转公开前扫了一遍全历史，发现 **6 条提交的作者邮箱是 QQ 邮箱**。
仓库一公开，这个邮箱就会随提交历史公开并被 GitHub 关联到账号。

趁还没公开，全部替换成了 `qinglisinianchun@users.noreply.github.com`。
**只改了邮箱字段，文件内容一个字节都没动**。现在远端历史里只剩两种安全邮箱：
账号自己的 noreply 地址和 GitHub 官方的机器人地址。

---

## 七、遗留事项

- **本地曾留的两份旧历史已随本机清理删除**（备份分支 + 完整副本目录）。远端历史已是最终形态。
- **WorkBuddy 里那条本机自动化 `基金漂移监控·每日巡检` 已停用**。
  **不要重新启用** —— 会和云端双跑、重复推微信，还会把 `last_run.txt` 写乱。
- **本机 staging 仓库与远端曾出现谱系分叉**（内容 tree 一致、提交 SHA 不同，
  因为 GitHub 会把作者日期归一化成 UTC）。本机副本已删，此问题随之消失。

---

## 八、排障速查

| 现象 | 先看哪 |
|---|---|
| 没收到微信 | ① Actions 里今天有没有跑 → ② 跑成功了说明**没触发**（正常）→ ③ 想验证通道就跑 `测试/测试推送.py` |
| Actions 报错 | `python tools/gh.py runs <repo> 5` 看 conclusion，再 `jobs` + `log` 抓真实日志 |
| 抓到 0 条净值 | 东财偶发抖动，不是封禁。看 `probe/探测结论.md` 里的实测数据 |
| 看板打不开 | `python tools/gh.py show <repo>` 看 Pages 状态 |
| 想本地复现 | clone 下来 `python run.py`，见第四节 |

### 判断「定时任务到底跑了没」

```bash
python tools/gh.py runs qinglisinianchun/fund-drift-monitor 10
```

`conclusion` 为 `success` 且时间对得上，就是跑了。定时任务延迟十几分钟到一小时都算正常。

---

**一句话总结**：项目在云端自转，你早上 7 点后看一眼手机就行；
想看细节开看板；要改东西，从第四节复制那条 clone 命令开始。
