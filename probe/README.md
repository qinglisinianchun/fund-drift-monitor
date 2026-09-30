# probe/ —— 可行性探测留档（2026-09-30）

**这里的东西不参与日常运行，只是当初把监控搬上 GitHub 之前的实测记录。**

要验证的前提问题：

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

一共跑了 6 轮 workflow，最后第 6 轮（head `7c57f90`）四个 job 全绿：内容验真 9/9、可靠性抽样 14/14。
云端抓到的净值（`080006` = 1.4156 / `2026-09-29`）比本机最后记录还新 **3 个交易日**。

## 探测任务

| 任务 | 脚本 | 干什么 |
|---|---|---|
| 探测外部接口可达性 | `scripts/probe-net.sh` | 逐项打所有接口，验 HTTP 状态 + 耗时 + 内容真伪 |
| 持仓接口专项复测 | `scripts/probe-holdings.sh` | 把 Referer / 参数 / HTTP 版本逐个拆开对比 |
| 接口可靠性抽样 | `scripts/probe-reliability.sh` | 重复打同一接口，算成功率 |
| 验证 runner 能否把数据写回仓库 | （原工作流内联） | 证明回写通道可用 |

原来的工作流 `probe-net.yml` 已归档成 `probe-net.yml.archived` ——
放在 `.github/workflows/` 之外，Actions 才不会把它当活跃工作流继续跑。

要重跑的话，把 `probe-net.yml.archived` 挪回 `.github/workflows/probe-net.yml` 即可。

## 四个坑（详见探测结论）

1. **持仓接口必须带 Referer** —— 不带直接 404；`type=jjcc` 必须小写。
2. **基金代码表是 http 明文会 301 跳转** —— curl 不加 `-L` 会拿到 0 字节，看起来像被拦。
3. **接口会偶发超时** —— 实测同一 URL 出现过「第 1 次成功、后面 5 次全超时」，
   换个时间重跑又 100% 成功。**不是封禁，是抖动，重试机制必须保留。**
4. **Windows 的 CRLF 会把 Linux 上的脚本跑挂** —— 本机 `core.autocrlf=true`，
   用 API 直推读工作区原始字节会绕过 git 的规范化，CRLF 进仓库后 runner 上 bash 报
   `syntax error: unexpected end of file`。已用 `.gitattributes`（`* text=auto eol=lf`）
   + `push-via-api.py` 走 `git hash-object` 双重保险。
   诊断用 `git ls-files --eol`，**别用 grep 数 `\r`**。

## 附带的推送工具

`scripts/push-to-github.sh` 和 `scripts/push-via-api.py` 是从这个项目里养出来的本机推送工具，
留在这一并归档：

```bash
# 正常推送（自动识别 VPN 代理；本仓库远端有自动提交，固定加 --rebase）
PUSH_COMMIT_MSG="提交信息" bash probe/scripts/push-to-github.sh qinglisinianchun fund-drift-monitor --rebase

# 兜底：github.com 被代理挡了、但 api.github.com 能通时，走 Git Data API 直推
python probe/scripts/push-via-api.py qinglisinianchun fund-drift-monitor main "提交信息" [--all]
```

> `api.github.com` 不带 `User-Agent` 一律返回 403 —— 不是被墙，别误判。

## 推不上去的时候

代理白名单会变。实测出现过 `api.github.com` 返回 200、而 `github.com`
报 `CONNECT tunnel failed, response 502` 的情况 —— 这时 `git push` 必然失败。
用 `push-via-api.py` 兜底即可。
