"""Unit tests for OmniSharp server wrapper.

These tests mock the subprocess and verify the OmniSharpServer logic
without requiring OmniSharp to be installed.
"""

import json
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest

from code_intel.lsp.omnisharp import (
    OmniSharpError,
    OmniSharpNotFoundError,
    OmniSharpServer,
    OmniSharpTimeoutError,
)
from code_intel.lsp.protocol import (
    CodeElement,
    CodeStructureResponse,
    GotoDefinitionResponse,
    QuickFix,
    QuickFixResponse,
)


class TestOmniSharpServerInit:
    """Tests for OmniSharpServer initialisation."""

    def test_init_with_valid_omnisharp_path(self, tmp_path: Path):
        """Test initialisation with a valid OmniSharp path."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        assert server.solution_path == solution.resolve()
        assert server.omnisharp_path == omnisharp
        assert server.timeout == 60.0

    def test_init_with_invalid_omnisharp_path(self, tmp_path: Path):
        """Test that initialisation fails with invalid OmniSharp path."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")

        with pytest.raises(OmniSharpNotFoundError) as exc_info:
            OmniSharpServer(solution, omnisharp_path="/nonexistent/omnisharp")

        assert "not found" in str(exc_info.value).lower()

    def test_init_with_custom_timeout(self, tmp_path: Path):
        """Test initialisation with custom timeout."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp, timeout=120.0)

        assert server.timeout == 120.0

    def test_init_resolves_solution_path(self, tmp_path: Path):
        """Test that solution path is resolved to absolute path."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(str(solution), omnisharp_path=omnisharp)

        assert server.solution_path.is_absolute()


class TestOmniSharpServerFindExecutable:
    """Tests for OmniSharp executable discovery."""

    def test_find_omnisharp_in_path(self, tmp_path: Path):
        """Test finding OmniSharp in system PATH."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")

        with mock.patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/omnisharp"

            server = OmniSharpServer(solution)

            assert server.omnisharp_path == Path("/usr/bin/omnisharp")

    def test_find_omnisharp_capitalised_in_path(self, tmp_path: Path):
        """Test finding OmniSharp (capitalised) in system PATH."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")

        with mock.patch("shutil.which") as mock_which:
            # First call for 'omnisharp' returns None, second for 'OmniSharp' succeeds
            mock_which.side_effect = [None, "/usr/bin/OmniSharp"]

            server = OmniSharpServer(solution)

            assert server.omnisharp_path == Path("/usr/bin/OmniSharp")

    def test_omnisharp_not_found_raises_error(self, tmp_path: Path):
        """Test that missing OmniSharp raises OmniSharpNotFoundError."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")

        with mock.patch("shutil.which", return_value=None):
            with mock.patch("glob.glob", return_value=[]):
                with pytest.raises(OmniSharpNotFoundError) as exc_info:
                    OmniSharpServer(solution)

                assert "not found" in str(exc_info.value).lower()


class TestOmniSharpServerSequenceNumbers:
    """Tests for sequence number generation."""

    def test_next_seq_increments(self, tmp_path: Path):
        """Test that sequence numbers increment correctly."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        seq1 = server._next_seq()
        seq2 = server._next_seq()
        seq3 = server._next_seq()

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_next_seq_thread_safety(self, tmp_path: Path):
        """Test that sequence number generation is thread-safe."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)
        sequences = []
        errors = []

        def get_sequences(count: int):
            try:
                for _ in range(count):
                    sequences.append(server._next_seq())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_sequences, args=(100,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sequences) == 500
        assert len(set(sequences)) == 500  # All unique


class TestOmniSharpServerStartStop:
    """Tests for server start and stop lifecycle."""

    def test_start_creates_process(self, tmp_path: Path):
        """Test that start creates a subprocess."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_process = mock.MagicMock()
        mock_process.stdin = mock.MagicMock()
        mock_process.stdout = mock.MagicMock()
        mock_process.stdout.read.return_value = b""

        with mock.patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            with mock.patch.object(server, "_wait_for_ready"):
                server.start()

                mock_popen.assert_called_once()
                call_args = mock_popen.call_args
                cmd = call_args[0][0]
                assert str(omnisharp) in cmd
                assert "-s" in cmd
                assert str(solution.resolve()) in cmd
                assert "--stdio" in cmd

    def test_start_when_already_running_logs_warning(self, tmp_path: Path, caplog):
        """Test that starting twice logs a warning."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)
        server._process = mock.MagicMock()  # Fake running process

        import logging

        with caplog.at_level(logging.WARNING):
            server.start()

        assert "already running" in caplog.text

    def test_stop_terminates_process(self, tmp_path: Path):
        """Test that stop terminates the subprocess."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_process = mock.MagicMock()
        mock_process.stdin = mock.MagicMock()
        server._process = mock_process
        server._running = True

        server.stop()

        mock_process.stdin.close.assert_called_once()
        mock_process.wait.assert_called()
        assert server._process is None
        assert server._running is False

    def test_stop_kills_unresponsive_process(self, tmp_path: Path):
        """Test that stop kills process if it doesn't terminate gracefully."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_process = mock.MagicMock()
        mock_process.stdin = mock.MagicMock()
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        server._process = mock_process
        server._running = True

        server.stop()

        mock_process.kill.assert_called_once()


class TestOmniSharpServerContextManager:
    """Tests for context manager protocol."""

    def test_context_manager_starts_and_stops(self, tmp_path: Path):
        """Test that context manager starts on enter and stops on exit."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        mock_process = mock.MagicMock()
        mock_process.stdin = mock.MagicMock()
        mock_process.stdout = mock.MagicMock()
        mock_process.stdout.read.return_value = b""

        with mock.patch("subprocess.Popen", return_value=mock_process):
            server = OmniSharpServer(solution, omnisharp_path=omnisharp)

            with mock.patch.object(server, "_wait_for_ready"):
                with mock.patch.object(server, "stop") as mock_stop:
                    with server as ctx:
                        assert ctx is server

                    mock_stop.assert_called_once()


class TestOmniSharpServerRequests:
    """Tests for request/response handling."""

    def test_send_request_builds_correct_message(self, tmp_path: Path):
        """Test that requests are formatted correctly."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_stdin = mock.MagicMock()
        mock_process = mock.MagicMock()
        mock_process.stdin = mock_stdin

        server._process = mock_process
        server._running = True

        seq = server._send_request_no_wait("/test", {"arg": "value"})

        assert seq == 1
        mock_stdin.write.assert_called_once()
        mock_stdin.flush.assert_called_once()

        # Verify message format
        written = mock_stdin.write.call_args[0][0]
        assert b"Content-Length:" in written
        assert b'"/test"' in written

    def test_send_request_without_process_raises_error(self, tmp_path: Path):
        """Test that sending request without process raises error."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        with pytest.raises(OmniSharpError) as exc_info:
            server._send_request_no_wait("/test", {})

        assert "not running" in str(exc_info.value).lower()


class TestOmniSharpServerProtocolMethods:
    """Tests for high-level protocol methods."""

    def test_get_code_structure_calls_correct_endpoint(self, tmp_path: Path):
        """Test that get_code_structure calls /v2/codestructure."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_response = mock.MagicMock()
        mock_response.body = {"Elements": []}
        mock_response.success = True

        with mock.patch.object(server, "_send_request", return_value=mock_response) as mock_send:
            result = server.get_code_structure("/path/to/file.cs")

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "/v2/codestructure"
            assert "FileName" in call_args[0][1]

            assert isinstance(result, CodeStructureResponse)

    def test_find_usages_calls_correct_endpoint(self, tmp_path: Path):
        """Test that find_usages calls /findusages."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_response = mock.MagicMock()
        mock_response.body = {"QuickFixes": []}
        mock_response.success = True

        with mock.patch.object(server, "_send_request", return_value=mock_response) as mock_send:
            result = server.find_usages("/path/to/file.cs", line=10, column=5)

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "/findusages"
            assert "FileName" in call_args[0][1]
            assert "Line" in call_args[0][1]
            assert "Column" in call_args[0][1]

            assert isinstance(result, QuickFixResponse)

    def test_goto_definition_calls_correct_endpoint(self, tmp_path: Path):
        """Test that goto_definition calls /v2/gotodefinition."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_response = mock.MagicMock()
        mock_response.body = {"Definitions": []}
        mock_response.success = True

        with mock.patch.object(server, "_send_request", return_value=mock_response) as mock_send:
            result = server.goto_definition("/path/to/file.cs", line=10, column=5)

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "/v2/gotodefinition"

            assert isinstance(result, GotoDefinitionResponse)

    def test_get_project_files_parses_msbuild_response(self, tmp_path: Path):
        """Test that get_project_files extracts files from MsBuild response."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)

        mock_response = mock.MagicMock()
        mock_response.body = {
            "MsBuild": {
                "Projects": [
                    {"SourceFiles": ["/path/to/File1.cs", "/path/to/File2.cs"]},
                    {"SourceFiles": ["/path/to/File3.cs"]},
                ]
            }
        }
        mock_response.success = True

        with mock.patch.object(server, "_send_request", return_value=mock_response):
            files = server.get_project_files()

            assert len(files) == 3
            assert "/path/to/File1.cs" in files
            assert "/path/to/File2.cs" in files
            assert "/path/to/File3.cs" in files


class TestOmniSharpServerTimeouts:
    """Tests for timeout handling."""

    def test_wait_for_ready_timeout(self, tmp_path: Path):
        """Test that _wait_for_ready raises timeout error."""
        solution = tmp_path / "Test.sln"
        solution.write_text("")
        omnisharp = tmp_path / "omnisharp"
        omnisharp.write_text("")
        omnisharp.chmod(0o755)

        server = OmniSharpServer(solution, omnisharp_path=omnisharp)
        server._running = True

        with mock.patch.object(
            server, "_send_request", side_effect=OmniSharpTimeoutError("timeout")
        ):
            with pytest.raises(OmniSharpTimeoutError):
                server._wait_for_ready(timeout=0.1)


class TestOmniSharpServerExceptions:
    """Tests for exception hierarchy."""

    def test_omnisharp_error_is_exception(self):
        """Test that OmniSharpError is an Exception."""
        error = OmniSharpError("test error")
        assert isinstance(error, Exception)

    def test_not_found_error_inherits_from_omnisharp_error(self):
        """Test that OmniSharpNotFoundError inherits from OmniSharpError."""
        error = OmniSharpNotFoundError("not found")
        assert isinstance(error, OmniSharpError)

    def test_timeout_error_inherits_from_omnisharp_error(self):
        """Test that OmniSharpTimeoutError inherits from OmniSharpError."""
        error = OmniSharpTimeoutError("timeout")
        assert isinstance(error, OmniSharpError)
