# -*- coding: utf-8 -*-
"""
一键运行：监控巡检 → 若触发则推送微信 → 刷新看板
自动化任务只需调用本脚本。
"""
import subprocess, sys, os

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def step(n, name, script):
    print(f'[{n}] {name} ...')
    subprocess.run([PY, os.path.join(BASE, script)], cwd=BASE)


step('1/3', '监控巡检', 'monitor.py')
step('2/3', '微信推送检查', 'notify.py')
step('3/3', '刷新看板', '生成看板.py')
print('\n✅ 全流程完成')
sys.exit(0)
