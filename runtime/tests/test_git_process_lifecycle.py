"""Run as container PID 1 to exercise Git's detached auto-maintenance.

python runtime/tests/test_git_process_lifecycle.py
On a regular host the Linux PID-1 integration case is skipped.
"""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

APP = Path(__file__).resolve().parents[1] / 'app.py'


def git_command_prefix():
    tree = ast.parse(APP.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'git')
    call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == 'run')
    prefix = []
    for item in call.args[0].elts:
        if isinstance(item, ast.Starred):
            break
        prefix.append(ast.literal_eval(item))
    return prefix


def zombie_git_children():
    found = []
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            value = stat.read_text()
            name = value[value.index('(') + 1:value.rindex(')')]
            fields = value[value.rindex(')') + 2:].split()
            if name == 'git' and fields[0] == 'Z' and int(fields[1]) == os.getpid():
                found.append(stat.parent.name)
        except (OSError, ValueError):
            continue
    return found


class GitProcessLifecycleTest(unittest.TestCase):
    def test_maintenance_stays_in_foreground(self):
        self.assertEqual(git_command_prefix(), ['git', '-c', 'maintenance.autoDetach=false',
                                               '-c', 'gc.autoDetach=false'])

    @unittest.skipUnless(os.path.isdir('/proc') and os.getpid() == 1, 'requires Linux container PID 1')
    def test_repeated_fetch_does_not_leave_orphan_zombies(self):
        before = set(zombie_git_children())
        with tempfile.TemporaryDirectory() as tmp:
            remote = Path(tmp) / 'remote.git'
            work = Path(tmp) / 'work'
            def git(*args):
                subprocess.run([*git_command_prefix(), *map(str, args)],
                               capture_output=True, check=True, timeout=30)
            git('init', '--bare', remote)
            git('clone', remote, work)
            for _ in range(20):
                git('-C', work, 'fetch', 'origin')
            time.sleep(0.5)
            self.assertEqual(set(zombie_git_children()) - before, set())


if __name__ == '__main__':
    unittest.main()
