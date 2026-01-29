"""OmniSharp server wrapper for C# semantic analysis.

This module provides a process manager for OmniSharp-Roslyn that handles:
- Starting and stopping the OmniSharp process
- Stdio transport communication (JSON lines protocol)
- Request/response matching via sequence numbers
- Waiting for solution projects to fully load before queries
- Querying /v2/codestructure and /findusages endpoints
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from code_intel.lsp.protocol import (
    CodeStructureRequest,
    CodeStructureResponse,
    FindUsagesRequest,
    GotoDefinitionRequest,
    GotoDefinitionResponse,
    OmniSharpRequest,
    OmniSharpResponse,
    QuickFixResponse,
)

logger = logging.getLogger(__name__)


class OmniSharpError(Exception):
    """Error from OmniSharp server."""

    pass


class OmniSharpNotFoundError(OmniSharpError):
    """OmniSharp executable not found."""

    pass


class OmniSharpTimeoutError(OmniSharpError):
    """OmniSharp request timed out."""

    pass


class OmniSharpServer:
    """Manages an OmniSharp-Roslyn server process for C# semantic analysis.

    This class handles the lifecycle of an OmniSharp process using stdio transport.
    It provides methods to query code structure and find usages of symbols.

    Usage:
        with OmniSharpServer("/path/to/solution.sln") as server:
            structure = server.get_code_structure("/path/to/File.cs")
            usages = server.find_usages("/path/to/File.cs", line=10, column=5)
    """

    DEFAULT_OMNISHARP_PATHS = [
        # Common installation paths
        "/usr/local/bin/omnisharp",
        "/usr/bin/omnisharp",
        # dotnet tool global install
        os.path.expanduser("~/.dotnet/tools/omnisharp"),
        # VS Code extension path (Linux)
        os.path.expanduser(
            "~/.vscode/extensions/ms-dotnettools.csharp-*/omnisharp/OmniSharp"
        ),
        # VS Code extension path (macOS)
        os.path.expanduser(
            "~/.vscode/extensions/ms-dotnettools.csharp-*/.omnisharp/*/OmniSharp"
        ),
    ]

    def __init__(
        self,
        solution_path: str | Path,
        omnisharp_path: str | Path | None = None,
        timeout: float = 60.0,
        project_load_timeout: float = 120.0,
    ):
        """Initialise OmniSharp server wrapper.

        Args:
            solution_path: Path to .sln file or directory containing .csproj files.
            omnisharp_path: Path to OmniSharp executable. If None, searches common paths.
            timeout: Default timeout for requests in seconds.
            project_load_timeout: Timeout for waiting for all projects to load in seconds.
                                  Set to 0 to skip waiting for projects.
        """
        self.solution_path = Path(solution_path).resolve()
        self.timeout = timeout
        self.project_load_timeout = project_load_timeout
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._pending_responses: dict[int, threading.Event] = {}
        self._responses: dict[int, OmniSharpResponse] = {}
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._read_lock = threading.Lock()

        # Project loading state
        self._projects_loaded: set[str] = set()
        self._projects_loaded_event = threading.Event()
        self._expected_project_count: int | None = None

        # Find OmniSharp executable
        if omnisharp_path:
            self.omnisharp_path = Path(omnisharp_path)
            if not self.omnisharp_path.exists():
                raise OmniSharpNotFoundError(
                    f"OmniSharp not found at: {self.omnisharp_path}"
                )
        else:
            self.omnisharp_path = self._find_omnisharp()

    def _find_omnisharp(self) -> Path:
        """Find OmniSharp executable in common locations.

        Returns:
            Path to OmniSharp executable.

        Raises:
            OmniSharpNotFoundError: If OmniSharp cannot be found.
        """
        # Check if omnisharp is in PATH
        omnisharp_in_path = shutil.which("omnisharp")
        if omnisharp_in_path:
            return Path(omnisharp_in_path)

        # Also check for OmniSharp (capitalised)
        omnisharp_cap_in_path = shutil.which("OmniSharp")
        if omnisharp_cap_in_path:
            return Path(omnisharp_cap_in_path)

        # Check common installation paths
        import glob

        for pattern in self.DEFAULT_OMNISHARP_PATHS:
            matches = glob.glob(pattern)
            for match in matches:
                path = Path(match)
                if path.exists() and path.is_file():
                    return path

        raise OmniSharpNotFoundError(
            "OmniSharp executable not found. Install via:\n"
            "  - dotnet tool install -g omnisharp\n"
            "  - VS Code C# extension\n"
            "  - Manual download from https://github.com/OmniSharp/omnisharp-roslyn"
        )

    def _next_seq(self) -> int:
        """Get next sequence number (thread-safe)."""
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _count_solution_projects(self) -> int:
        """Count the number of projects in the solution file.

        Parses the .sln file to count Project entries. If the solution_path
        is a .csproj file or directory, returns 1 as we expect a single project.

        Returns:
            Number of expected projects in the solution.
        """
        if not self.solution_path.suffix.lower() == ".sln":
            # Single .csproj or directory - expect 1 project
            return 1

        if not self.solution_path.exists():
            logger.warning("Solution file not found: %s", self.solution_path)
            return 0

        try:
            content = self.solution_path.read_text(encoding="utf-8-sig")

            # Match Project lines in .sln file
            # Format: Project("{GUID}") = "Name", "Path.csproj", "{GUID}"
            # We look for .csproj, .fsproj, .vbproj extensions
            project_pattern = re.compile(
                r'^Project\s*\(\s*"\{[^}]+\}"\s*\)\s*=\s*"[^"]+"\s*,\s*"([^"]+\.(csproj|fsproj|vbproj))"',
                re.MULTILINE | re.IGNORECASE,
            )

            projects = project_pattern.findall(content)
            count = len(projects)

            logger.debug(
                "Found %d projects in solution %s", count, self.solution_path.name
            )
            return count

        except OSError as e:
            logger.warning("Failed to read solution file: %s", e)
            return 0

    def start(self) -> None:
        """Start the OmniSharp server process.

        Waits for the server to become responsive (via /checkalivestatus) and then
        waits for all solution projects to finish loading before returning. This
        ensures that queries like /findusages will return complete results.

        Raises:
            OmniSharpError: If the server fails to start.
        """
        if self._process is not None:
            logger.warning("OmniSharp server already running")
            return

        # Reset project loading state
        self._projects_loaded.clear()
        self._projects_loaded_event.clear()
        self._expected_project_count = self._count_solution_projects()

        cmd = [
            str(self.omnisharp_path),
            "-s",
            str(self.solution_path),
            "--stdio",  # Use stdio transport
            "--encoding",
            "utf-8",
        ]

        logger.info("Starting OmniSharp: %s", " ".join(cmd))
        logger.info(
            "Expecting %d projects to load from solution",
            self._expected_project_count,
        )

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # Unbuffered for stdio protocol
            )
        except OSError as e:
            raise OmniSharpError(f"Failed to start OmniSharp: {e}") from e

        self._running = True

        # Start reader thread
        self._reader_thread = threading.Thread(
            target=self._read_responses, daemon=True, name="omnisharp-reader"
        )
        self._reader_thread.start()

        # Wait for server to be ready (responds to /checkalivestatus)
        logger.info("Waiting for OmniSharp to initialise...")
        self._wait_for_ready()
        logger.info("OmniSharp server alive")

        # Wait for all projects to load (tracks ProjectAdded events)
        if self.project_load_timeout > 0 and self._expected_project_count > 0:
            self._wait_for_projects_loaded()

        logger.info("OmniSharp server ready with %d projects", len(self._projects_loaded))

    def _wait_for_ready(self, timeout: float = 120.0) -> None:
        """Wait for OmniSharp to respond to requests.

        This only checks that the server is alive and accepting requests.
        It does NOT wait for projects to finish loading - use _wait_for_projects_loaded()
        for that.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            OmniSharpTimeoutError: If server doesn't become ready in time.
        """
        start = time.time()
        while time.time() - start < timeout:
            if not self._running:
                raise OmniSharpError("OmniSharp process terminated unexpectedly")
            # OmniSharp is ready when we can successfully send a request
            try:
                # Send a simple request to check if server is ready
                self._send_request("/checkalivestatus", {}, timeout=5.0)
                return
            except OmniSharpTimeoutError:
                time.sleep(1.0)
                continue
            except OmniSharpError:
                time.sleep(1.0)
                continue

        raise OmniSharpTimeoutError(
            f"OmniSharp server did not become ready within {timeout} seconds"
        )

    def _wait_for_projects_loaded(self) -> None:
        """Wait for all projects in the solution to finish loading.

        Monitors ProjectAdded events from OmniSharp and waits until the expected
        number of projects have loaded, or until the timeout is reached.

        For large solutions (e.g., PLOD with ~800 files), project loading can take
        20-30 seconds after the server responds to /checkalivestatus.
        """
        if self._expected_project_count is None or self._expected_project_count <= 0:
            logger.debug("No expected projects, skipping wait")
            return

        logger.info(
            "Waiting for %d projects to load (timeout: %.1fs)...",
            self._expected_project_count,
            self.project_load_timeout,
        )

        start = time.time()

        while time.time() - start < self.project_load_timeout:
            if not self._running:
                raise OmniSharpError("OmniSharp process terminated unexpectedly")

            loaded_count = len(self._projects_loaded)
            if loaded_count >= self._expected_project_count:
                elapsed = time.time() - start
                logger.info(
                    "All %d projects loaded in %.1f seconds",
                    loaded_count,
                    elapsed,
                )
                return

            # Wait for the event with a short timeout to allow periodic logging
            if self._projects_loaded_event.wait(timeout=5.0):
                # Event was set, check if we have all projects
                self._projects_loaded_event.clear()
                continue

            # Log progress periodically
            elapsed = time.time() - start
            logger.debug(
                "Loaded %d/%d projects (%.1fs elapsed)",
                loaded_count,
                self._expected_project_count,
                elapsed,
            )

        # Timeout reached
        loaded_count = len(self._projects_loaded)
        if loaded_count < self._expected_project_count:
            logger.warning(
                "Timeout waiting for projects: loaded %d/%d after %.1f seconds. "
                "Proceeding anyway - some queries may return incomplete results.",
                loaded_count,
                self._expected_project_count,
                self.project_load_timeout,
            )
        else:
            logger.info(
                "All %d projects loaded (timeout check passed)",
                loaded_count,
            )

    def stop(self) -> None:
        """Stop the OmniSharp server process."""
        self._running = False

        if self._process:
            logger.info("Stopping OmniSharp server")
            try:
                # Send stopserver command
                self._send_request_no_wait("/stopserver", {})
            except Exception:
                pass

            # Close stdin to signal shutdown
            if self._process.stdin:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass

            # Wait for process to terminate
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.warning("OmniSharp didn't terminate gracefully, killing")
                self._process.kill()
                self._process.wait()

            self._process = None

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

        logger.info("OmniSharp server stopped")

    def __enter__(self) -> OmniSharpServer:
        """Context manager entry - start server."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - stop server."""
        self.stop()

    def _handle_event(self, event_name: str, body: dict[str, Any]) -> None:
        """Handle an OmniSharp event.

        Tracks ProjectAdded events to monitor solution loading progress.

        Args:
            event_name: Name of the event (e.g., "ProjectAdded", "MsBuildProjectDiagnostics").
            body: Event body containing event-specific data.
        """
        if event_name == "ProjectAdded":
            # Extract project path from the event body
            # OmniSharp sends: {"MsBuildProject": {"Path": "...", "AssemblyName": "..."}}
            # or directly: {"Path": "...", "AssemblyName": "..."}
            project_info = body.get("MsBuildProject", body)
            project_path = project_info.get("Path", project_info.get("path", ""))

            if project_path:
                with self._read_lock:
                    if project_path not in self._projects_loaded:
                        self._projects_loaded.add(project_path)
                        logger.debug(
                            "Project loaded (%d/%s): %s",
                            len(self._projects_loaded),
                            self._expected_project_count or "?",
                            Path(project_path).name,
                        )
                        # Signal that a project was loaded
                        self._projects_loaded_event.set()
            else:
                logger.debug("ProjectAdded event without path: %s", body)

        elif event_name == "MsBuildProjectDiagnostics":
            # Log any MSBuild diagnostics (warnings/errors during project load)
            file_path = body.get("FileName", body.get("fileName", ""))
            diagnostics = body.get("Diagnostics", body.get("diagnostics", []))
            if diagnostics:
                for diag in diagnostics[:3]:  # Limit logging
                    severity = diag.get("LogLevel", diag.get("logLevel", ""))
                    message = diag.get("Message", diag.get("message", ""))
                    if severity.lower() == "error":
                        logger.warning(
                            "MSBuild error in %s: %s", Path(file_path).name, message
                        )

        elif event_name in ("log", "Log"):
            # Standard log event
            log_level = body.get("LogLevel", body.get("logLevel", ""))
            message = body.get("Message", body.get("message", ""))
            if log_level.lower() == "error":
                logger.error("OmniSharp: %s", message)
            else:
                logger.debug("OmniSharp %s: %s", log_level, message[:200] if message else "")

        else:
            logger.debug("OmniSharp event: %s", event_name)

    def _read_responses(self) -> None:
        """Background thread to read responses from OmniSharp stdout.

        OmniSharp --stdio mode uses newline-delimited JSON (JSON lines),
        not the LSP Content-Length protocol.
        """
        if not self._process or not self._process.stdout:
            return

        import io

        # Wrap stdout in a text reader for line-based reading
        stdout = io.TextIOWrapper(self._process.stdout, encoding="utf-8", errors="replace")

        while self._running:
            try:
                # Read one JSON line
                line = stdout.readline()
                if not line:
                    logger.debug("OmniSharp stdout closed")
                    self._running = False
                    return

                line = line.strip()
                if not line:
                    continue

                # Parse JSON response
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON response: %s - line: %s", e, line[:100])
                    continue

                # Handle different message types
                msg_type = data.get("Type", data.get("type", ""))

                if msg_type == "event":
                    event_name = data.get("Event", data.get("event", ""))
                    self._handle_event(event_name, data.get("Body", {}))
                    continue

                if msg_type == "response":
                    # Match response to request
                    request_seq = data.get("Request_seq", data.get("request_seq"))
                    if request_seq is not None:
                        try:
                            response = OmniSharpResponse.model_validate(data)
                            with self._read_lock:
                                self._responses[request_seq] = response
                                if request_seq in self._pending_responses:
                                    self._pending_responses[request_seq].set()
                        except Exception as e:
                            logger.warning("Failed to parse response: %s", e)
                    continue

                logger.debug("Unknown message type: %s", msg_type)

            except Exception as e:
                if self._running:
                    logger.warning("Error reading from OmniSharp: %s", e)
                break

    def _send_request_no_wait(
        self, command: str, arguments: dict[str, Any]
    ) -> int:
        """Send a request without waiting for response.

        Args:
            command: OmniSharp command endpoint.
            arguments: Request arguments.

        Returns:
            Sequence number of the request.
        """
        if not self._process or not self._process.stdin:
            raise OmniSharpError("OmniSharp server not running")

        seq = self._next_seq()

        request = OmniSharpRequest(
            seq=seq,
            command=command,
            arguments=arguments,
        )

        # Serialise with OmniSharp field names
        request_data = request.model_dump(by_alias=True, exclude_none=True)

        # OmniSharp --stdio uses JSON lines (newline-delimited JSON)
        message = json.dumps(request_data) + "\n"

        try:
            self._process.stdin.write(message.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise OmniSharpError(f"Failed to send request: {e}") from e

        return seq

    def _send_request(
        self,
        command: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> OmniSharpResponse:
        """Send a request and wait for response.

        Args:
            command: OmniSharp command endpoint.
            arguments: Request arguments.
            timeout: Timeout in seconds (uses default if None).

        Returns:
            OmniSharp response.

        Raises:
            OmniSharpTimeoutError: If request times out.
            OmniSharpError: If request fails.
        """
        timeout = timeout if timeout is not None else self.timeout

        # Create event for this request
        seq = self._next_seq()
        event = threading.Event()

        with self._read_lock:
            self._pending_responses[seq] = event

        # Send request
        if not self._process or not self._process.stdin:
            raise OmniSharpError("OmniSharp server not running")

        request = OmniSharpRequest(
            seq=seq,
            command=command,
            arguments=arguments,
        )

        request_data = request.model_dump(by_alias=True, exclude_none=True)
        # OmniSharp --stdio uses JSON lines (newline-delimited JSON)
        message = json.dumps(request_data) + "\n"

        try:
            self._process.stdin.write(message.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            with self._read_lock:
                self._pending_responses.pop(seq, None)
            raise OmniSharpError(f"Failed to send request: {e}") from e

        # Wait for response
        if not event.wait(timeout=timeout):
            with self._read_lock:
                self._pending_responses.pop(seq, None)
            raise OmniSharpTimeoutError(
                f"Request {command} timed out after {timeout} seconds"
            )

        # Get response
        with self._read_lock:
            self._pending_responses.pop(seq, None)
            response = self._responses.pop(seq)

        if not response.success:
            raise OmniSharpError(
                f"Request {command} failed: {response.message or 'Unknown error'}"
            )

        return response

    def get_code_structure(self, file_path: str | Path) -> CodeStructureResponse:
        """Get the code structure for a file.

        Args:
            file_path: Path to the C# file.

        Returns:
            CodeStructureResponse with hierarchical code elements.
        """
        file_path = Path(file_path).resolve()

        request = CodeStructureRequest(file_name=str(file_path))
        response = self._send_request(
            "/v2/codestructure",
            request.model_dump(by_alias=True),
        )

        if response.body is None:
            return CodeStructureResponse(elements=None)

        return CodeStructureResponse.model_validate(response.body)

    def find_usages(
        self,
        file_path: str | Path,
        line: int,
        column: int,
        only_this_file: bool = False,
        exclude_definition: bool = True,
    ) -> QuickFixResponse:
        """Find all usages of a symbol.

        Args:
            file_path: Path to the C# file.
            line: 0-indexed line number of the symbol.
            column: 0-indexed column number of the symbol.
            only_this_file: Whether to limit search to this file.
            exclude_definition: Whether to exclude the definition from results.

        Returns:
            QuickFixResponse with all found usages.
        """
        file_path = Path(file_path).resolve()

        request = FindUsagesRequest(
            file_name=str(file_path),
            line=line,
            column=column,
            only_this_file=only_this_file,
            exclude_definition=exclude_definition,
        )
        response = self._send_request(
            "/findusages",
            request.model_dump(by_alias=True),
        )

        if response.body is None:
            return QuickFixResponse(quick_fixes=None)

        return QuickFixResponse.model_validate(response.body)

    def goto_definition(
        self,
        file_path: str | Path,
        line: int,
        column: int,
    ) -> GotoDefinitionResponse:
        """Go to the definition of a symbol.

        Args:
            file_path: Path to the C# file.
            line: 0-indexed line number of the symbol.
            column: 0-indexed column number of the symbol.

        Returns:
            GotoDefinitionResponse with definition locations.
        """
        file_path = Path(file_path).resolve()

        request = GotoDefinitionRequest(
            file_name=str(file_path),
            line=line,
            column=column,
        )
        response = self._send_request(
            "/v2/gotodefinition",
            request.model_dump(by_alias=True),
        )

        if response.body is None:
            return GotoDefinitionResponse(definitions=None)

        return GotoDefinitionResponse.model_validate(response.body)

    def get_project_files(self) -> list[str]:
        """Get all C# files in the solution/project.

        Returns:
            List of file paths.
        """
        response = self._send_request("/projects", {})

        files = []
        if response.body:
            # Extract files from MsBuild projects
            msbuild = response.body.get("MsBuild", {})
            projects = msbuild.get("Projects", [])
            for project in projects:
                source_files = project.get("SourceFiles", [])
                files.extend(source_files)

        return files
