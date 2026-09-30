# fund-drift-monitor

纳指平替漂移监控 —— GitHub Actions 托管版。

## 当前阶段：可行性探测 —— 已通过 ✅

监控代码还没搬上来。这里先验证一个前提问题：

> **本机能访问的接口，GitHub Actions 的 runner 能不能访问？**

本机在河北、走 VPN；runner 在弗吉尼亚 Azure 机房。这条链路不通，后面所有设计都是白搭。

**结论：完全可行。** 详见 [`探测结论.md`](探测结论.md)。

| 接口 | 结果 |
|---|---|
| 东财净值 `api.fund.eastmoney.com/f10/lsjz` | ✅ 抽样 6/6 成功 |
| 东财持仓 `fundf10.eastmoney.com/FundArchivesDatas.aspx` | ✅ 抽样 4/4 成功 |
| 东财基金代码全表（http 明文） | ✅ 3.18 MB / 28000 个代码 |
| 东财费率页 | ✅ 40.5 KB |
| 微信 Server酱 推送通道 | ✅ 发送接口返回正常业务响应 |
| runner 回写仓库（`git push`） | ✅ 成功 |

云端抓到的净值（`080006` 1.4156 / 2026-09-29）比本机最后记录新了 **3 个交易日**。

## 探测任务

| 任务 | 脚本 | 干什么 |
|---|---|---|
| 探测外部接口可达性 | `scripts/probe-net.sh` | 逐项打所有接口，验 HTTP 状态 + 耗时 + 内容真伪 |
| 持仓接口专项复测 | `scripts/probe-holdings.sh` | 把 Referer / 参数 / HTTP 版本逐个拆开对比 |
| 接口可靠性抽样 | `scripts/probe-reliability.sh` | 重复打同一接口，算成功率 |
| 验证 runner 能否把数据写回仓库 | （工作流内联） | 证明回写通道可用 |

## 怎么跑

```bash
# 方式一：手动触发
gh workflow run probe-net.yml

# 方式二：改脚本推上去，自动触发
PUSH_COMMIT_MSG="test(probe): ..." bash scripts/push-to-github.sh qinglisinianchun fund-drift-monitor --rebase
```

> **这个仓库固定加 `--rebase`。** 里面有云端任务会往回写数据，远端天天有新提交；
> 不加的话脚本会停下来问，加了就自动安全叠加（本地未提交的改动会暂存再还原，不会丢）。

## 三个坑（详见探测结论）

1. **持仓接口必须带 Referer** —— 不带直接 404；`type=jjcc` 必须小写。
2. **基金代码表是 http 明文会 301 跳转** —— curl 不加 `-L` 会拿到 0 字节，看起来像被拦。
3. **接口会偶发超时** —— 实测同一 URL 出现过「第 1 次成功、后面 5 次全超时」，
   换个时间重跑又 100% 成功。**不是封禁，是抖动，重试机制必须保留。**

## 目录

```
探测结论.md                        完整实测结论（含环境、数据、对策）
.github/workflows/probe-net.yml    探测工作流（4 个任务）
scripts/probe-net.sh               逐项接口探测 + 内容验真
scripts/probe-holdings.sh          持仓接口变量拆解
scripts/probe-reliability.sh       成功率抽样
scripts/push-to-github.sh          推送脚本（自动识别 VPN 代理，支持 --rebase）
scripts/push-via-api.py            兜底：github.com 被挡、但 api.github.com 能通时直推
```

## 推不上去的时候

代理白名单会变。实测出现过 `api.github.com` 返回 200、而 `github.com`
报 `CONNECT tunnel failed, response 502` 的情况 —— 这时 `git push` 必然失败。

用 API 直推兜底：

```bash
python scripts/push-via-api.py qinglisinianchun fund-drift-monitor main "提交信息"
python scripts/push-via-api.py qinglisinianchun fund-drift-monitor main "提交信息" --all
```

`--all` = 把本地所有 git 跟踪的文件整份同步上去（本地有若干提交没推上去时用）。

