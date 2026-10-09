import importlib.util
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('setup', Path(__file__).parents[1] / 'headless-ai-mac.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

ACCOUNT = SimpleNamespace(pw_name='server', pw_uid=501, pw_gid=20, pw_dir='/Users/server')


class ScreenSharingTests(unittest.TestCase):
    def test_setup_preserves_screen_sharing(self):
        self.assertNotIn('com.apple.screensharing', setup.LAUNCH_AGENTS_TO_DISABLE)
        with patch.object(setup, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            setup.disable_unnecessary_services()
        for call in run.call_args_list:
            cmd = call.args[0]
            self.assertFalse('disable' in cmd and any('screensharing' in arg for arg in cmd))

    def test_restore_can_recover_older_installations(self):
        self.assertIn('com.apple.screensharing', setup.RESTORE_LAUNCH_AGENTS)


class OllamaSetupTests(unittest.TestCase):
    def test_sudo_uses_original_account_not_root_home(self):
        with patch.dict(os.environ, {'SUDO_USER': 'server', 'HOME': '/var/root'}, clear=True), \
             patch.object(setup.pwd, 'getpwnam', return_value=ACCOUNT) as lookup, \
             patch.object(Path, 'is_dir', return_value=True):
            self.assertEqual(setup.resolve_ollama_account(), ACCOUNT)
            lookup.assert_called_once_with('server')

    def test_root_requires_explicit_non_root_user(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(setup.os, 'getuid', return_value=0):
            with self.assertRaisesRegex(RuntimeError, '--user'):
                setup.resolve_ollama_account()
        with patch.object(setup.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=0)):
            with self.assertRaises(RuntimeError):
                setup.resolve_ollama_account('root')

    def test_plist_has_account_home_models_and_limits(self):
        for ram, parallel in [(64, '1'), (128, '2')]:
            config = setup.build_ollama_plist(ACCOUNT, '/path/with & spaces/ollama', ram, '/data/models')
            config = plistlib.loads(plistlib.dumps(config))
            self.assertEqual(config['UserName'], 'server')
            self.assertEqual(config['EnvironmentVariables']['HOME'], '/Users/server')
            self.assertEqual(config['EnvironmentVariables']['OLLAMA_MODELS'], '/data/models')
            self.assertEqual(config['EnvironmentVariables']['OLLAMA_MAX_LOADED_MODELS'], '1')
            self.assertEqual(config['EnvironmentVariables']['OLLAMA_NUM_PARALLEL'], parallel)

    def test_existing_model_directory_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'service.plist'
            path.write_bytes(plistlib.dumps({'EnvironmentVariables': {'OLLAMA_MODELS': '/custom/models'}}))
            self.assertEqual(setup.ollama_models_path(ACCOUNT, path), '/custom/models')
            path.unlink()
            self.assertEqual(setup.ollama_models_path(ACCOUNT, path), '/Users/server/.ollama/models')

    def test_competing_listener_aborts(self):
        with patch.object(setup, 'ollama_listener_pids', return_value={123}), \
             patch.object(setup, 'ollama_daemon_pid', return_value=456):
            with self.assertRaisesRegex(RuntimeError, '123'):
                setup.check_ollama_port()

    def test_own_listener_allowed_for_rerun(self):
        with patch.object(setup, 'ollama_listener_pids', return_value={456}), \
             patch.object(setup, 'ollama_daemon_pid', return_value=456):
            setup.check_ollama_port()

    def test_log_files_reowned_without_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ollama.err'
            path.write_text('existing error\n')
            with patch.object(setup.os, 'chown') as chown:
                setup.prepare_ollama_logs(ACCOUNT, [path])
            chown.assert_called_once_with(path, 501, 20)
            self.assertEqual(path.read_text(), 'existing error\n')

    def test_health_requires_listener_matching_daemon(self):
        with patch.object(setup, 'ollama_daemon_pid', return_value=456), \
             patch.object(setup, 'ollama_listener_pids', return_value={123}), \
             patch.object(setup.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'start'):
                setup.wait_for_ollama(attempts=2)
        with patch.object(setup, 'ollama_daemon_pid', return_value=456), \
             patch.object(setup, 'ollama_listener_pids', return_value={456}):
            self.assertEqual(setup.wait_for_ollama(), 456)

    def test_configuration_checks_bootstrap_and_orders_logs_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'daemon.plist'
            with patch.object(setup, 'check_ollama_port'), \
                 patch.object(setup, 'prepare_ollama_logs') as logs, \
                 patch.object(setup.os, 'chown'), \
                 patch.object(setup, 'wait_for_ollama', return_value=456), \
                 patch.object(setup, 'run') as run:
                def command(cmd, **kwargs):
                    if 'bootstrap' in cmd:
                        logs.assert_called_once()
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                run.side_effect = command
                setup.configure_ollama_launchd(64, ACCOUNT, '/bin/ollama', path)
                logs.assert_called_once()
                calls = [call.args[0] for call in run.call_args_list]
                self.assertIn(['launchctl', 'bootstrap', 'system', str(path)], calls)
                self.assertLess(calls.index(['launchctl', 'bootout', 'system/com.ollama.headless']),
                                calls.index(['launchctl', 'bootstrap', 'system', str(path)]))
                bootstrap = next(call for call in run.call_args_list if 'bootstrap' in call.args[0])
                self.assertTrue(bootstrap.kwargs.get('check', True))
                self.assertEqual(plistlib.loads(path.read_bytes())['UserName'], 'server')

    def test_bootstrap_failure_propagates_without_success(self):
        def command(cmd, **kwargs):
            if 'bootstrap' in cmd:
                raise RuntimeError('bootstrap failed')
            return SimpleNamespace(returncode=1, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(setup, 'check_ollama_port'), \
                 patch.object(setup, 'prepare_ollama_logs'), \
                 patch.object(setup.os, 'chown'), \
                 patch.object(setup, 'info') as info, \
                 patch.object(setup, 'run', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'bootstrap failed'):
                    setup.configure_ollama_launchd(64, ACCOUNT, '/bin/ollama', Path(directory) / 'daemon.plist')
                info.assert_not_called()

    def test_bootout_failure_aborts_before_overwriting_config(self):
        def command(cmd, **kwargs):
            if 'bootout' in cmd:
                raise RuntimeError('bootout failed')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'daemon.plist'
            original = plistlib.dumps({'EnvironmentVariables': {}})
            path.write_bytes(original)
            with patch.object(setup, 'check_ollama_port'), \
                 patch.object(setup, 'prepare_ollama_logs') as logs, \
                 patch.object(setup, 'run', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'bootout failed'):
                    setup.configure_ollama_launchd(64, ACCOUNT, '/bin/ollama', path)
                logs.assert_not_called()
                self.assertEqual(path.read_bytes(), original)

    def test_log_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ollama.err'
            path.symlink_to(Path(directory) / 'target')
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                setup.prepare_ollama_logs(ACCOUNT, [path])

    def test_lsof_empty_is_free_but_errors_abort(self):
        with patch.object(setup, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='')):
            self.assertEqual(setup.ollama_listener_pids(), set())
        with patch.object(setup, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='permission denied')):
            with self.assertRaises(RuntimeError):
                setup.ollama_listener_pids()

    def test_daemon_pid_missing_and_running(self):
        with patch.object(setup, 'run', return_value=SimpleNamespace(returncode=0, stdout='state = spawn scheduled\n')):
            self.assertIsNone(setup.ollama_daemon_pid())
        with patch.object(setup, 'run', return_value=SimpleNamespace(returncode=0, stdout='state = running\n\tpid = 456\n')):
            self.assertEqual(setup.ollama_daemon_pid(), 456)

    def test_unknown_user_fails(self):
        with patch.object(setup.pwd, 'getpwnam', side_effect=KeyError):
            with self.assertRaisesRegex(RuntimeError, 'Unknown account'):
                setup.resolve_ollama_account('missing')

    def test_binary_check_does_not_execute_ollama_cli(self):
        with patch.object(setup, 'find_ollama_binary', return_value='/bin/ollama'), \
             patch.object(setup, 'check_ollama_port'), \
             patch.object(setup, 'run') as run:
            self.assertEqual(setup.check_prerequisites(), '/bin/ollama')
            run.assert_not_called()

    def test_ollama_only_skips_unrelated_system_changes(self):
        with patch.object(setup.sys, 'argv', ['headless-ai-mac.py', '--ollama-only']), \
             patch.object(setup.platform, 'system', return_value='Darwin'), \
             patch.object(setup, 'require_sudo'), \
             patch.object(setup, 'resolve_ollama_account', return_value=ACCOUNT), \
             patch.object(setup, 'check_prerequisites', return_value='/bin/ollama'), \
             patch.object(setup, 'detect_hardware', return_value={'ram_gb': 64}), \
             patch.object(setup, 'confirm', return_value=True), \
             patch.object(setup, 'configure_ollama_launchd') as configure, \
             patch.object(setup, 'disable_unnecessary_services') as services, \
             patch.object(setup, 'configure_vram') as vram, \
             patch.object(setup, 'install_homebrew') as brew:
            setup.main()
            configure.assert_called_once_with(64, ACCOUNT, '/bin/ollama')
            services.assert_not_called()
            vram.assert_not_called()
            brew.assert_not_called()


if __name__ == '__main__':
    unittest.main()
