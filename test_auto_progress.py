#!/usr/bin/env python3
"""Unit tests for auto_progress.py — progress extraction and wrapping."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add script to path
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import auto_progress


class TestExtractProgress(unittest.TestCase):
    """Test the extract_progress function with various output formats."""

    def test_wget_percent(self):
        """wget: ' 45% '"""
        self.assertEqual(auto_progress.extract_progress(" 45% [========================>..."), 45)
        self.assertEqual(auto_progress.extract_progress("100% [=============================]"), 100)

    def test_make_brackets(self):
        """make: '[ 55%]' or '[55%]'"""
        self.assertEqual(auto_progress.extract_progress("[ 55%] Building foo.o"), 55)
        self.assertEqual(auto_progress.extract_progress("[55%] Building bar.o"), 55)

    def test_cmake_brackets(self):
        """cmake: same bracket format"""
        self.assertEqual(auto_progress.extract_progress("[ 75%] Built target foo"), 75)

    def test_pip_hash(self):
        """pip: '### 45.0%'"""
        self.assertEqual(auto_progress.extract_progress("### 45.0%"), 45)

    def test_git_clone(self):
        """git clone: 'Receiving objects:  45%'"""
        self.assertEqual(auto_progress.extract_progress("Receiving objects:  45% (123/456)"), 45)

    def test_git_resolving(self):
        """git: 'Resolving deltas: 80%'"""
        self.assertEqual(auto_progress.extract_progress("Resolving deltas: 80% (1000/1250)"), 80)

    def test_conda_hash(self):
        """conda: '#45.0%'"""
        self.assertEqual(auto_progress.extract_progress("#45.0% |################################  | 45/100"), 45)

    def test_apt_progress(self):
        """apt: 'Progress: [###  >   ] 45%'"""
        self.assertEqual(auto_progress.extract_progress("Progress: [#######################>] 45%"), 45)

    def test_curl_mb(self):
        """curl: '45.2 MB / 100.0 MB'"""
        self.assertEqual(auto_progress.extract_progress("45.2 MB / 100.0 MB"), 45)

    def test_curl_full_mb(self):
        """curl: '100.0 MB / 100.0 MB'"""
        self.assertEqual(auto_progress.extract_progress("100.0 MB / 100.0 MB"), 100)

    def test_counter_generic(self):
        """Generic counter: '45/100 files'"""
        self.assertEqual(auto_progress.extract_progress("45/100 files"), 45)

    def test_counter_no_label(self):
        """Generic counter: '45/100'"""
        self.assertEqual(auto_progress.extract_progress("45/100"), 45)

    def test_counter_complete(self):
        """Generic counter complete: '100/100'"""
        self.assertEqual(auto_progress.extract_progress("100/100"), 100)

    def test_rsync(self):
        """rsync progress: '     45%    1.2MB/s    0:00:05'"""
        self.assertEqual(auto_progress.extract_progress("     45%    1.2MB/s    0:00:05"), 45)

    def test_no_progress(self):
        """Normal output with no progress pattern."""
        self.assertIsNone(auto_progress.extract_progress("Hello, world!"))
        self.assertIsNone(auto_progress.extract_progress("Downloading file..."))
        self.assertIsNone(auto_progress.extract_progress("[INFO] Build started"))

    def test_zero_percent(self):
        """Zero percent."""
        self.assertEqual(auto_progress.extract_progress("   0% "), 0)

    def test_edge_percent_99(self):
        """99% - edge case."""
        self.assertEqual(auto_progress.extract_progress("  99% "), 99)

    def test_ffmpeg_no_extract(self):
        """ffmpeg frames — extract returns None (no total frame count)"""
        self.assertIsNone(auto_progress.extract_progress("frame=  245 fps= 30 q=28.0 size=    4096kB time=00:00:08.16"))


class TestFormatProgressBar(unittest.TestCase):
    """Test the progress bar formatting."""

    def test_progress_bar_0(self):
        bar = auto_progress.format_progress_bar(0, width=10)
        self.assertIn("0%", bar)
        self.assertIn("░" * 10, bar)

    def test_progress_bar_50(self):
        bar = auto_progress.format_progress_bar(50, width=10)
        self.assertIn("50%", bar)
        self.assertIn("█" * 5, bar)
        self.assertIn("░" * 5, bar)

    def test_progress_bar_100(self):
        bar = auto_progress.format_progress_bar(100, width=10)
        self.assertIn("100%", bar)
        self.assertIn("█" * 10, bar)

    def test_progress_bar_custom_width(self):
        bar = auto_progress.format_progress_bar(25, width=20)
        self.assertIn("█" * 5, bar)
        self.assertIn("░" * 15, bar)


class TestDetectLongCommand(unittest.TestCase):
    """Test detection of long-running commands."""

    def _make_args(self, cmd_list):
        from argparse import Namespace
        args = Namespace()
        args.command = cmd_list
        return args

    def test_wget_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['wget', '-c', 'url'])))

    def test_make_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['make', '-j16'])))

    def test_pip_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['pip', 'install', 'numpy'])))

    def test_git_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['git', 'clone', 'repo'])))

    def test_curl_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['curl', '-O', 'url'])))

    def test_rsync_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['rsync', '-av', 'src/', 'dst/'])))

    def test_dd_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['dd', 'if=/dev/zero', 'of=file', 'bs=1M'])))

    def test_npm_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['npm', 'install', 'express'])))

    def test_cargo_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['cargo', 'build', '--release'])))

    def test_ls_not_detected(self):
        self.assertFalse(auto_progress.detect_long_command(self._make_args(['ls', '-la'])))

    def test_echo_not_detected(self):
        self.assertFalse(auto_progress.detect_long_command(self._make_args(['echo', 'hello'])))

    def test_cat_not_detected(self):
        self.assertFalse(auto_progress.detect_long_command(self._make_args(['cat', 'file.txt'])))

    def test_apt_get_detected(self):
        self.assertTrue(auto_progress.detect_long_command(self._make_args(['apt-get', 'install', '-y', 'python3'])))


class TestAutoWrapCommand(unittest.TestCase):
    """Test the auto_wrap_command function."""

    def test_wget_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("wget -c https://example.com/file")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'wget'", wrapped)
        self.assertIn("wget -c https://example.com/file", wrapped)

    def test_make_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("make -j16")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'make'", wrapped)

    def test_echo_not_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("echo hello")
        self.assertEqual(wrapped, "echo hello")

    def test_ls_not_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("ls -la")
        self.assertEqual(wrapped, "ls -la")

    def test_empty_not_wrapped(self):
        self.assertEqual(auto_progress.auto_wrap_command(""), "")
        self.assertEqual(auto_progress.auto_wrap_command(None), None)

    def test_pip_install_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("pip install torch torchvision")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'pip'", wrapped)

    def test_git_clone_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("git clone https://github.com/org/repo")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'git'", wrapped)

    def test_conda_install_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("conda install numpy")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'conda'", wrapped)

    def test_apt_get_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("apt-get install -y python3")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'apt-get'", wrapped)

    def test_rsync_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("rsync -av src/ dst/")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'rsync'", wrapped)

    def test_cargo_build_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("cargo build --release")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'cargo'", wrapped)

    def test_dd_wrapped(self):
        wrapped = auto_progress.auto_wrap_command("dd if=/dev/zero of=test bs=1M count=100 status=progress")
        self.assertIn("auto_progress.py", wrapped)
        self.assertIn("--tool 'dd'", wrapped)


class TestPushProgress(unittest.TestCase):
    """Test the push_progress function (sidecar HTTP call)."""

    @patch('auto_progress.urllib.request.urlopen')
    def test_push_progress_basic(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        auto_progress.push_progress("download", 45, "45% done", 300, "msg123")
        mock_urlopen.assert_called_once()
        call_args, call_kwargs = mock_urlopen.call_args
        self.assertIn("/progress", str(call_args[0].full_url))
        body = json.loads(call_args[0].data)
        self.assertEqual(body["tool_id"], "download")
        self.assertEqual(body["percent"], 45)
        self.assertEqual(body["detail"], "45% done")
        self.assertEqual(body["eta"], 300)
        self.assertEqual(body["message_id"], "msg123")

    @patch('auto_progress.urllib.request.urlopen')
    def test_push_progress_with_title(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        auto_progress.push_progress("download", 50, "Halfway", 150, "msg456", "Downloading Model")
        call_args, _ = mock_urlopen.call_args
        body = json.loads(call_args[0].data)
        self.assertEqual(body["title"], "Downloading Model")

    @patch('auto_progress.urllib.request.urlopen')
    def test_push_progress_silent_failure(self, mock_urlopen):
        """Sidecar might be down — should fail silently."""
        mock_urlopen.side_effect = ConnectionError("Connection refused")
        auto_progress.push_progress("download", 45, "test")
        mock_urlopen.assert_called_once()

    @patch('auto_progress.urllib.request.urlopen')
    def test_push_progress_zero_percent(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        auto_progress.push_progress("download", 0, "Starting...")
        call_args, _ = mock_urlopen.call_args
        body = json.loads(call_args[0].data)
        self.assertEqual(body["percent"], 0)

    @patch('auto_progress.urllib.request.urlopen')
    def test_push_progress_100_percent(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        auto_progress.push_progress("download", 100, "Done!")
        call_args, _ = mock_urlopen.call_args
        body = json.loads(call_args[0].data)
        self.assertEqual(body["percent"], 100)


class TestRunWithProgress(unittest.TestCase):
    """Test the run_with_progress function (subprocess execution)."""

    def test_command_not_found(self):
        """Non-existent command should exit with 1."""
        from argparse import Namespace
        args = Namespace()
        args.command = ['_nonexistent_cmd_XYZ123_']
        args.tool = 'test'
        args.interval = 5
        args.message_id = ''
        args.foreground = False
        args.title = ''

        with self.assertRaises((SystemExit, PermissionError, FileNotFoundError)):
            auto_progress.run_with_progress(args)

    def test_successful_command(self):
        """Simple one-shot command should run and exit 0."""
        from argparse import Namespace
        args = Namespace()
        args.command = ['echo', 'hello']
        args.tool = 'test'
        args.interval = 5
        args.message_id = ''
        args.foreground = False
        args.title = ''

        exit_code = auto_progress.run_with_progress(args)
        self.assertEqual(exit_code, 0)

    def test_failing_command(self):
        """Command that exits non-zero."""
        from argparse import Namespace
        args = Namespace()
        args.command = ['false']
        args.tool = 'test'
        args.interval = 5
        args.message_id = ''
        args.foreground = False
        args.title = ''

        exit_code = auto_progress.run_with_progress(args)
        self.assertEqual(exit_code, 1)

    def test_echo_with_foreground(self):
        """Foreground mode should work."""
        from argparse import Namespace
        args = Namespace()
        args.command = ['echo', 'hello']
        args.tool = 'test'
        args.interval = 5
        args.message_id = ''
        args.foreground = True
        args.title = 'My Task'

        exit_code = auto_progress.run_with_progress(args)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
