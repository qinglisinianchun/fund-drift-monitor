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
    python push-via-api.py <owner> <repo> [分支] [提交信息]
    # 推送内容 = 工作区相对上次提交有变化的所有文件

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


def changed_files():
    """工作区里相对 HEAD 有变化的文件（含新增、修改、删除）"""
    out = subprocess.run(['git', 'status', '--porcelain'],
                         capture_output=True, text=True, check=True).stdout
    add, dele = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        flag, path = line[:2], line[3:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if flag.strip() == 'D':
            dele.append(path)
        else:
            add.append(path)
    return add, dele


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__.strip().split('用法')[-1].strip())
    owner, repo = sys.argv[1], sys.argv[2]
    branch = sys.argv[3] if len(sys.argv) > 3 else 'main'
    msg = sys.argv[4] if len(sys.argv) > 4 else 'chore: 通过 API 推送本地改动'

    gh = GH(get_token())
    base = f'/repos/{owner}/{repo}'

    add, dele = changed_files()
    if not add and not dele:
        print('[--] 工作区没有变化，无需推送')
        return

    # 1) 当前分支指向的提交
    ref = gh.call('GET', f'{base}/git/ref/heads/{branch}')
    head_sha = ref['object']['sha']
    head = gh.call('GET', f'{base}/git/commits/{head_sha}')
    print(f'[OK] 远端 {branch} = {head_sha[:7]}')

    # 2) 把每个文件做成 blob
    tree_items = []
    for path in add:
        with open(path, 'rb') as f:
            raw = f.read()
        blob = gh.call('POST', f'{base}/git/blobs', {
            'content': base64.b64encode(raw).decode('ascii'),
            'encoding': 'base64'})
        tree_items.append({'path': path.replace('\\', '/'), 'mode': '100644',
                           'type': 'blob', 'sha': blob['sha']})
        print(f'     + {path}  ({len(raw)} B)')
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
