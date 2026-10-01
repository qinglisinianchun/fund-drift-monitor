# -*- coding: utf-8 -*-
"""
github.com 被代理挡住、只有 api.github.com 能通时，用 Git Data API 把
【改写过的提交历史】整条重新上传，并把分支指针强制指过去。

为什么不用重传文件：
    这次改写只动了 commit 的 author/committer 邮箱，tree 与 blob 一个字节都没变，
    它们的 SHA 与远端已有的对象完全相同 —— 所以只要重建 commit 对象即可。
    一个 commit 一次 API 调用，25 个提交也就 25 次，很轻。

用法：
    python reupload-history.py <owner/repo> <branch> [--dry-run]
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh import api  # noqa: E402

# 用 ASCII 的 0x1f / 0x1e 做分隔符。
# 不能用 \x00 —— Windows 的 CreateProcess 不接受命令行参数里含 NUL 字符。
SEP = '\x1e'
FLD = '\x1f'
FMT = FLD.join(['%H', '%T', '%P', '%an', '%ae', '%aI', '%cn', '%ce', '%cI', '%B']) + SEP


def local_commits(branch):
    """按从老到新返回本地提交。"""
    raw = subprocess.run(
        ['git', 'log', f'--format={FMT}', '--reverse', branch],
        capture_output=True, text=True, encoding='utf-8', check=True).stdout
    out = []
    for rec in raw.split(SEP):
        rec = rec.strip('\n')
        if not rec:
            continue
        parts = rec.split(FLD)
        if len(parts) < 10:
            continue
        sha, tree, parents, an, ae, ad, cn, ce, cd, msg = parts[:10]
        out.append({
            'old': sha, 'tree': tree,
            'parents': parents.split() if parents else [],
            'author': {'name': an, 'email': ae, 'date': ad},
            'committer': {'name': cn, 'email': ce, 'date': cd},
            'message': msg.rstrip('\n'),
        })
    return out


def main():
    repo, branch = sys.argv[1], sys.argv[2]
    dry = '--dry-run' in sys.argv

    commits = local_commits(branch)
    print(f'本地 {branch} 共 {len(commits)} 个提交，准备重建\n')

    # 远端现有对象（tree 是否都在，先验证头尾两个）
    for c in (commits[0], commits[-1]):
        st, obj = api('GET', f'/repos/{repo}/git/trees/{c["tree"]}')
        print(f'  tree {c["tree"][:10]} 存在性检查 → HTTP {st}')

    if dry:
        print('\n[dry-run] 到此为止，未改动远端。')
        return

    # 远端当前 main，稍后用于 force-with-lease 式的安全检查
    st, ref = api('GET', f'/repos/{repo}/git/ref/heads/{branch}')
    old_head = ref['object']['sha']
    print(f'\n远端 {branch} 当前 = {old_head}')

    mapping, new_parents = {}, []
    for i, c in enumerate(commits, 1):
        body = {
            'message': c['message'],
            'tree': c['tree'],
            'parents': new_parents,
            'author': c['author'],
            'committer': c['committer'],
        }
        st, d = api('POST', f'/repos/{repo}/git/commits', body)
        mapping[c['old']] = d['sha']
        new_parents = [d['sha']]
        flag = '' if c['old'] == d['sha'] else '  ← SHA 已变'
        print(f'  [{i:>2}/{len(commits)}] {c["old"][:8]} → {d["sha"][:8]}'
              f'  {c["message"].splitlines()[0][:44]}{flag}')

    new_head = new_parents[0]
    print(f'\n新 {branch} = {new_head}')

    # 安全检查：远端指针必须还是我们刚才读到的那个，防止覆盖别人的提交
    st, ref2 = api('GET', f'/repos/{repo}/git/ref/heads/{branch}')
    if ref2['object']['sha'] != old_head:
        raise SystemExit(f'[x] 远端 {branch} 在我们操作期间被改动了'
                         f'（{old_head} → {ref2["object"]["sha"]}），已中止。')

    st, d = api('PATCH', f'/repos/{repo}/git/refs/heads/{branch}',
                {'sha': new_head, 'force': True})
    print(f'✅ 已强制更新 {branch} → {new_head[:8]}（HTTP {st}）')


if __name__ == '__main__':
    main()
