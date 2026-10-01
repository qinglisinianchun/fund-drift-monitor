# -*- coding: utf-8 -*-
"""
fund-drift-monitor 的 GitHub 运维小工具（放在仓库外，不会被提交）。

子命令：
  secret  <owner/repo> <NAME> <value>     写 Actions secret（libsodium sealed box）
  public  <owner/repo>                    把仓库改成公开
  pages   <owner/repo> [branch] [path]    开启 GitHub Pages（默认 main / 根目录）
  run     <owner/repo> <workflow.yml>     手动触发 workflow_dispatch
  runs    <owner/repo> [数量]             列出最近的 workflow run
  log     <owner/repo> <job_id>           打印某个 job 的日志（纯文本）
  show    <owner/repo>                    仓库可见性 / Pages 状态

令牌：环境变量 GITHUB_TOKEN，没设就从 Windows 凭据管理器读（与 git 用的是同一份）。
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

API = 'https://api.github.com'
UA = 'fund-drift-monitor-tools'


def get_token():
    tok = os.environ.get('GITHUB_TOKEN', '').strip()
    if tok:
        return tok
    cmd = ['git']
    gcm = shutil.which('git-credential-manager')
    if gcm:
        gcm = gcm.replace('\\', '/')
        cmd += ['-c', 'credential.helper=', '-c', f'credential.helper=!"{gcm}"']
    cmd += ['-c', 'credential.interactive=false', 'credential', 'fill']
    inp = 'protocol=https\nhost=github.com\n\n'
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    out = subprocess.run(cmd, input=inp, capture_output=True, text=True, env=env)
    for line in out.stdout.splitlines():
        if line.startswith('password='):
            return line[len('password='):].strip()
    raise SystemExit('[x] 取不到 GitHub 令牌。\n' + out.stdout + out.stderr)


TOKEN = None


def api(method, path, body=None, raw=False, expect=(200, 201, 204)):
    global TOKEN
    if TOKEN is None:
        TOKEN = get_token()
    url = path if path.startswith('http') else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': UA,
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            payload = r.read()
            if raw:
                return r.status, payload.decode('utf-8', 'replace')
            return r.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as e:
        payload = e.read().decode('utf-8', 'replace')
        if e.code in expect:
            return e.code, payload
        raise SystemExit(f'[x] HTTP {e.code} {method} {url}\n{payload}')


# --------------------------------------------------------------------------
def cmd_secret(repo, name, value):
    st, key = api('GET', f'/repos/{repo}/actions/secrets/public-key')
    from nacl import encoding, public
    pk = public.PublicKey(key['key'].encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    st, _ = api('PUT', f'/repos/{repo}/actions/secrets/{name}',
                {'encrypted_value': enc, 'key_id': key['key_id']})
    print(f'  ✅ secret {name} 已写入（HTTP {st}）')


def cmd_public(repo):
    st, d = api('PATCH', f'/repos/{repo}', {'private': False})
    print(f'  ✅ 仓库可见性 = {"private" if d.get("private") else "public"}')

    st, d = api('GET', f'/repos/{repo}')
    print(f'     完整名: {d["full_name"]}   默认分支: {d["default_branch"]}')
    print(f'     地址:   {d["html_url"]}')


def cmd_pages(repo, branch='main', path='/'):
    st, d = api('POST', f'/repos/{repo}/pages',
                {'source': {'branch': branch, 'path': path}},
                expect=(201, 409))
    if st == 409:
        st, d = api('PUT', f'/repos/{repo}/pages',
                    {'source': {'branch': branch, 'path': path}})
        print('  (Pages 已存在，改为更新配置)')
    print(f'  ✅ Pages 已开启（HTTP {st}）   source = {branch}:{path}')


def cmd_show(repo):
    st, d = api('GET', f'/repos/{repo}')
    print(f'仓库      : {d["full_name"]}')
    print(f'可见性    : {"私有" if d["private"] else "公开"}')
    print(f'默认分支  : {d["default_branch"]}')
    print(f'大小      : {d.get("size")} KB')
    st, p = api('GET', f'/repos/{repo}/pages', expect=(200, 404))
    if st == 404:
        print('Pages     : 未开启')
    else:
        print(f'Pages     : {p.get("status")}  →  {p.get("html_url")}')
    st, s = api('GET', f'/repos/{repo}/actions/secrets', expect=(200,))
    print('Secrets   : ' + (', '.join(x['name'] for x in s.get('secrets', [])) or '（无）'))
    st, w = api('GET', f'/repos/{repo}/actions/workflows')
    for x in w.get('workflows', []):
        print(f'  workflow: {x["name"]:<10} state={x["state"]:<12} {x["path"]}')


def cmd_run(repo, wf):
    st, d = api('POST', f'/repos/{repo}/actions/workflows/{wf}/dispatches',
                {'ref': 'main'}, expect=(204,))
    print(f'  ✅ 已触发 {wf}（HTTP {st}）')


def cmd_runs(repo, n=5):
    st, d = api('GET', f'/repos/{repo}/actions/runs?per_page={n}')
    for r in d.get('workflow_runs', []):
        print(f'  #{r["run_number"]:<4} id={r["id"]:<12} {r["name"]:<10} '
              f'{r["status"]:<12} {r["conclusion"] or "-":<10} {r["created_at"]}  {r["head_sha"][:7]}')
    return d.get('workflow_runs', [])


def cmd_jobs(repo, run_id):
    st, d = api('GET', f'/repos/{repo}/actions/runs/{run_id}/jobs')
    for j in d.get('jobs', []):
        print(f'  job id={j["id"]}  {j["name"]}  {j["status"]}/{j["conclusion"]}')
        for s in j.get('steps', []):
            print(f'      - {s["name"]:<32} {s["status"]}/{s["conclusion"]}')
    return d.get('jobs', [])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """日志接口会 302 跳到带签名的 Azure Blob 地址；
    带着 Authorization 头去访问那个地址会被拒（401 InvalidAuthenticationInfo）。
    所以这里禁用自动跳转，手动拿 Location 再裸访问。"""

    def redirect_request(self, *a, **k):
        return None


def fetch_log(url):
    global TOKEN
    if TOKEN is None:
        TOKEN = get_token()
    op = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': UA,
    })
    try:
        with op.open(req, timeout=45) as r:
            return r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get('Location')
            if not loc:
                raise SystemExit('[x] 日志接口重定向但没有 Location')
            with urllib.request.urlopen(loc, timeout=120) as r2:
                return r2.read().decode('utf-8', 'replace')
        raise SystemExit(f'[x] HTTP {e.code} 取日志失败\n'
                         + e.read().decode('utf-8', 'replace')[:500])


def cmd_log(repo, job_id):
    print(fetch_log(f'{API}/repos/{repo}/actions/jobs/{job_id}/logs'))


def cmd_logrun(repo, run_id):
    st, d = api('GET', f'/repos/{repo}/actions/runs/{run_id}/jobs')
    for j in d.get('jobs', []):
        print(f'\n########## {j["name"]} ({j["conclusion"]}) ##########')
        print(fetch_log(f'{API}/repos/{repo}/actions/jobs/{j["id"]}/logs'))


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(1)
    c = a[0]
    if c == 'secret':
        cmd_secret(a[1], a[2], a[3])
    elif c == 'public':
        cmd_public(a[1])
    elif c == 'pages':
        cmd_pages(*a[1:])
    elif c == 'show':
        cmd_show(a[1])
    elif c == 'run':
        cmd_run(a[1], a[2])
    elif c == 'runs':
        cmd_runs(a[1], int(a[2]) if len(a) > 2 else 5)
    elif c == 'jobs':
        cmd_jobs(a[1], a[2])
    elif c == 'log':
        cmd_log(a[1], a[2])
    elif c == 'logrun':
        cmd_logrun(a[1], a[2])
    else:
        print(__doc__)
        sys.exit(1)
