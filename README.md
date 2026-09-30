# fund-drift-monitor

纳指平替漂移监控 —— GitHub Actions 托管版。

## 这个仓库现在是干什么的

**当前阶段：网络可行性探测。** 还没有搬监控代码上来。

目的：验证 GitHub Actions 的 runner 能不能访问监控所需的全部外部接口。
本机（河北，走 VPN）能访问，不代表 GitHub 的机器（多在境外）也能访问 ——
这一关过不了，后面所有设计都是白搭。

## 探测哪些接口

| 项 | 接口 | 用途 |
|---|---|---|
| 1 | `api.fund.eastmoney.com/f10/lsjz` | 历史净值，监控命脉 |
| 2 | `fund.eastmoney.com/js/fundcode_search.js` | 基金代码全表（**http 明文**） |
| 3 | `fundf10.eastmoney.com/FundArchivesDatas.aspx` | 持仓穿透 |
| 4 | `fundf10.eastmoney.com/jjfl_*.html` | 费率页 |
| 5 | `sctapi.ftqq.com` | 微信 Server酱 推送通道 |

## 怎么跑

```bash
gh workflow run probe-net.yml
# 或直接在网页 Actions 页面点 Run workflow
```

只探测、无副作用 —— 不带 Server酱 key，不会真的发出微信推送。

## 目录

```
.github/workflows/probe-net.yml   探测工作流
scripts/probe-net.sh              探测脚本（逐项打印 HTTP 状态/耗时/响应片段 + 内容验真）
```
