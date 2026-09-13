import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


recovery = load('recovery', ROOT / 'files/recovery.py')
local = load('local', ROOT / 'scripts/local.py')


class Tests(unittest.TestCase):
    def test_targets_separate_application_profiles_from_agent_logs(self):
        inv = {'_meta': {'hostvars': {'app3': {
            'pprotein_collect_http': True, 'pprotein_collect_sql': True, 'pprotein_collect_go': True,
            'pprotein_tunnel_log_port': 19103, 'pprotein_tunnel_go_port': 19203}}}}
        targets, commands = local.configuration(inv, ['app3'], 60)
        self.assertIn(':19203/debug/pprof/profile', targets[-1]['URL'])
        self.assertIn(':19103/debug/log/slowlog', targets[1]['URL'])
        self.assertEqual(commands[0].count('-L'), 2)
        self.assertIn('127.0.0.1:19203:127.0.0.1:19001', commands[0])

    def test_port_collision_is_rejected(self):
        host = {'pprotein_collect_http': True, 'pprotein_tunnel_log_port': 19101}
        with self.assertRaises(ValueError):
            local.configuration({'_meta': {'hostvars': {'a': host, 'b': host}}}, ['a', 'b'], 10)

    def test_snapshot_restore_preserves_files_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / 'agent', root / 'env', root / 'service']
            paths[0].write_bytes(b'old executable')
            paths[0].chmod(0o750)
            paths[2].write_text('old service')
            def ctl(*args, **kwargs):
                return {'is-active': 'active', 'is-enabled': 'enabled'}.get(args[0], '')
            with patch.object(recovery, 'FILES', paths), patch.object(recovery, 'systemctl', side_effect=ctl) as calls:
                recovery.snapshot(root / 'snapshot')
                paths[0].write_bytes(b'new executable')
                paths[1].write_text('new env')
                recovery.restore(root / 'snapshot')
                self.assertEqual(paths[0].read_bytes(), b'old executable')
                self.assertFalse(paths[1].exists())
                self.assertEqual(paths[0].stat().st_mode & 0o777, 0o750)
                count = calls.call_count
                recovery.restore(root / 'snapshot')
                self.assertEqual(calls.call_count, count)

    def test_corrupt_backup_never_stops_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / 'agent', root / 'env', root / 'service']
            paths[0].write_bytes(b'original')
            with patch.object(recovery, 'FILES', paths), patch.object(recovery, 'systemctl', return_value='inactive') as ctl:
                def state(*args, **kwargs):
                    return 'inactive' if args[0] == 'is-active' else 'disabled'
                ctl.side_effect = state
                recovery.snapshot(root / 'backup')
                (root / 'backup/0').write_bytes(b'corrupt')
                ctl.reset_mock()
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    recovery.restore(root / 'backup')
                ctl.assert_not_called()

    def test_old_snapshot_is_rejected_before_service_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / 'agent', root / 'env', root / 'service']
            with patch.object(recovery, 'FILES', paths), patch.object(recovery, 'systemctl') as ctl:
                ctl.side_effect = lambda *args, **kwargs: 'inactive' if args[0] == 'is-active' else 'disabled'
                recovery.snapshot(root / 'first')
                recovery.snapshot(root / 'second')
                ctl.reset_mock()
                with self.assertRaisesRegex(RuntimeError, 'old snapshot'):
                    recovery.restore(root / 'first')
                ctl.assert_not_called()


if __name__ == '__main__':
    unittest.main()
