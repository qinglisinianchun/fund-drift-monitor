# -*- coding: utf-8 -*-
"""
当 github.com 被网络策略挡住、但 api.github.com 还能通时，用 Git Data API 推送提交。

背景（2026-09-30 实测）
----------------------
沙箱/办公网的代理白名单会变动。实测出现过：
    api.github.com   → HTTP 200
    github.com       → CONNECT tunnel failed, response 502（走代理）
                     → 直连 20 秒超时
此时 `git push` 必然失败，因为它连的是 github.com。
但 GitHub 的 REST API 在 api.github.com 上，可以把「创建 blob → 建 tree → 建 commit
→ 移动 ref」这一串走完，效果等同于一次推送。

用法
----
    python push-via-api.py <owner> <repo> [分支] [提交信息] [--all]

    默认：只推工作区里相对 HEAD 有变化的文件（相当于 git add -A && commit && push）
    --all：把本地【所有 git 跟踪的文件】整份同步上去
           （当本地有若干提交没推上去、而远端又被云端任务写过数据时用这个）

令牌来源：环境变量 GITHUB_TOKEN；没设就读 Windows 凭据管理器里的 GitHub 凭据
（与 git 用的是同一份，见技能 github-proxy-and-secrets）。
"""

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = 'https://api.github.com'


def get_token():
    tok = os.environ.get('GITHUB_TOKEN', '').strip()
    if tok:
        return tok
    # 从 Windows 凭据管理器读（GCM 存的，git push 用的就是它）
    p = subprocess.run(
        ['git', '-c', 'credential.interactive=false', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n',
        capture_output=True, text=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'})
    for line in p.stdout.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise SystemExit('[x] 取不到 GitHub 令牌。设 GITHUB_TOKEN 环境变量，或先让 git 记住凭据。')


class GH:
    def __init__(self, token):
        self.t = token

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            # api.github.com 不带 User-Agent 一律 403
            'User-Agent': 'push-via-api',
            'Authorization': 'Bearer ' + self.t,
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read().decode('utf-8')
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            raise SystemExit(f'[x] {method} {path} → HTTP {e.code}\n{e.read().decode("utf-8", "replace")[:600]}')


def _z(args):
    """跑 git 并拿到 NUL 分隔的输出。

    必须用 -z：git 默认 core.quotepath=true，中文文件名会被转义成
    '"\\346\\216\\242..."' 这种带引号的八进制串，直接 open() 会报
    OSError: Invalid argument。
    """
    out = subprocess.run(args, capture_output=True, check=True).stdout
    return [x.decode('utf-8') for x in out.split(b'\0') if x]


def blob_bytes(path):
    """拿到「git 规范化之后」的文件字节，而不是工作区的原始字节。

    这一步是必须的，不是优化。踩过的坑（2026-09-30）：
      本机 core.autocrlf=true，工作区里的 .sh 是 CRLF；正常 git commit 会在入库时
      把 CRLF 转回 LF，而直接用 open() 读工作区字节会【绕过】这层转换，
      于是 CRLF 进了仓库 —— Linux runner 上 bash 报：
          set: pipefail / invalid option name
          $'\\r': command not found
          syntax error: unexpected end of file
      实测就是这么把两个脚本跑挂的。

      `git hash-object -w --path=<p> <p>` 会按 .gitattributes / autocrlf 做一遍
      与 commit 完全相同的转换并把对象写进本地对象库，再用 cat-file 读回来，
      拿到的字节就与 git push 的结果一致了。
    """
    sha = subprocess.run(['git', 'hash-object', '-w', '--path', path, path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return subprocess.run(['git', 'cat-file', 'blob', sha],
                          capture_output=True, check=True).stdout


def changed_files():
    """工作区里相对 HEAD 有变化的文件（含新增、修改、删除）"""
    fields = _z(['git', 'status', '--porcelain', '-z'])
    add, dele = [], []
    i = 0
    while i < len(fields):
        entry = fields[i]
        flag, path = entry[:2], entry[3:]
        i += 1
        if flag[:1] in ('R', 'C'):      # 重命名/复制：后面还跟着原路径，跳过
            i += 1
        (dele if flag.strip() == 'D' else add).append(path)
    return add, dele


def tracked_files():
    """本地所有 git 跟踪的文件"""
    return _z(['git', 'ls-files', '-z'])


def main():
    argv = [a for a in sys.argv[1:] if a != '--all']
    use_all = '--all' in sys.argv[1:]

    if len(argv) < 2:
        raise SystemExit(__doc__.strip().split('用法')[-1].strip())
    owner, repo = argv[0], argv[1]
    branch = argv[2] if len(argv) > 2 else 'main'
    msg = argv[3] if len(argv) > 3 else 'chore: 通过 API 推送本地改动'

    gh = GH(get_token())
    base = f'/repos/{owner}/{repo}'

    if use_all:
        add, dele = tracked_files(), []
    else:
        add, dele = changed_files()
    if not add and not dele:
        print('[--] 工作区没有变化，无需推送')
        return
    print(f'[--] 待上传 {len(add)} 个文件（--all={"是" if use_all else "否"}）')

    # 1) 当前分支指向的提交
    ref = gh.call('GET', f'{base}/git/ref/heads/{branch}')
    head_sha = ref['object']['sha']
    head = gh.call('GET', f'{base}/git/commits/{head_sha}')
    print(f'[OK] 远端 {branch} = {head_sha[:7]}')

    # 2) 把每个文件做成 blob
    tree_items = []
    warned = 0
    for path in add:
        raw = blob_bytes(path)
        # 兜底告警：规范化之后文本文件里还不该有 CRLF。
        # 真出现了说明 .gitattributes 没覆盖到，Linux 上的脚本会挂。
        if path.lower().endswith(('.sh', '.yml', '.yaml', '.py', '.md', '.txt', '.json')) \
                and b'\r\n' in raw:
            print(f'     ⚠️  {path} 规范化后仍含 CRLF —— 检查 .gitattributes')
            warned += 1
        blob = gh.call('POST', f'{base}/git/blobs', {
            'content': base64.b64encode(raw).decode('ascii'),
            'encoding': 'base64'})
        tree_items.append({'path': path.replace('\\', '/'), 'mode': '100644',
                           'type': 'blob', 'sha': blob['sha']})
        print(f'     + {path}  ({len(raw)} B)')
    if warned:
        print(f'[!] {warned} 个文件换行符异常，建议先跑 git add --renormalize .')
    for path in dele:
        # sha=None + mode 100644 表示删除
        tree_items.append({'path': path.replace('\\', '/'), 'mode': '100644',
                           'type': 'blob', 'sha': None})
        print(f'     - {path}')

    # 3) 新 tree（base_tree = 在远端现有内容之上叠加，不会丢别的文件）
    tree = gh.call('POST', f'{base}/git/trees', {
        'base_tree': head['tree']['sha'], 'tree': tree_items})

    # 4) 新 commit
    commit = gh.call('POST', f'{base}/git/commits', {
        'message': msg, 'tree': tree['sha'], 'parents': [head_sha]})

    # 5) 移动分支指针
    gh.call('PATCH', f'{base}/git/refs/heads/{branch}',
            {'sha': commit['sha'], 'force': False})

    print(f'[OK] 推送完成 {head_sha[:7]} → {commit["sha"][:7]}')
    print(f'     https://github.com/{owner}/{repo}/commit/{commit["sha"]}')


if __name__ == '__main__':
    main()
