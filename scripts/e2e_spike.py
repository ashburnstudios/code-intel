#!/usr/bin/env python3
"""End-to-end spike test for code-intel.

Validates the full pipeline against real Python projects:
- memoria: Smaller project for initial validation
- gateway-mcp: Medium complexity, plugin architecture

Success Criteria:
- Can index memoria without errors
- Can index gateway-mcp without errors
- find_callers returns sensible results
- find_references returns sensible results
- Indexing completes in < 30 seconds per project
- Queries complete in < 100ms
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_intel import CodeIntelClient, get_python_parser


@dataclass
class TestResult:
    """Result of a test case."""

    name: str
    passed: bool
    duration_ms: float
    details: str = ""
    error: str | None = None


@dataclass
class SpikeResults:
    """Aggregated results from the spike test."""

    tests: list[TestResult] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    missing_for_phase2: list[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.passed)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if not t.passed)

    def add_test(self, result: TestResult) -> None:
        self.tests.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name} ({result.duration_ms:.1f}ms)")
        if result.details:
            for line in result.details.split("\n"):
                print(f"       {line}")
        if result.error:
            print(f"       ERROR: {result.error}")


def measure(func):
    """Decorator to measure execution time."""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = (time.perf_counter() - start) * 1000
        return result, duration
    return wrapper


class E2ESpike:
    """End-to-end spike test runner."""

    def __init__(self):
        self.results = SpikeResults()
        self.client = CodeIntelClient()  # In-memory DB for testing
        self.client.register_parser(get_python_parser())
        self.memoria_path = Path.home() / "Projects" / "memoria"
        self.gateway_path = Path.home() / "Projects" / "gateway-mcp"

    def run(self) -> SpikeResults:
        """Run all spike tests."""
        print("\n" + "=" * 70)
        print("CODE-INTEL END-TO-END SPIKE TEST")
        print("=" * 70)

        # Test 1: Index memoria
        print("\n[1/6] Indexing memoria...")
        self._test_index_memoria()

        # Test 2: Query memoria - find_callers
        print("\n[2/6] Testing find_callers on memoria...")
        self._test_find_callers_memoria()

        # Test 3: Query memoria - find_references
        print("\n[3/6] Testing find_references on memoria...")
        self._test_find_references_memoria()

        # Test 4: Get stats for memoria
        print("\n[4/6] Getting stats for memoria...")
        self._test_stats_memoria()

        # Test 5: Index gateway-mcp (scale test)
        print("\n[5/6] Indexing gateway-mcp (scale test)...")
        self._test_index_gateway()

        # Test 6: Query gateway-mcp
        print("\n[6/6] Testing queries on gateway-mcp...")
        self._test_queries_gateway()

        # Summary
        self._print_summary()

        return self.results

    def _test_index_memoria(self) -> None:
        """Test indexing memoria project."""
        if not self.memoria_path.exists():
            self.results.add_test(TestResult(
                name="Index memoria",
                passed=False,
                duration_ms=0,
                error=f"Project not found: {self.memoria_path}",
            ))
            return

        files_indexed = []

        def progress(current: int, total: int, path: str) -> None:
            files_indexed.append(path)
            if current % 10 == 0 or current == total:
                print(f"       [{current}/{total}] {Path(path).name}")

        start = time.perf_counter()
        try:
            result = self.client.index_repo(
                self.memoria_path,
                force=True,
                progress_callback=progress,
            )
            duration = (time.perf_counter() - start) * 1000

            passed = result.files_failed == 0 and duration < 30000
            details = (
                f"Files: {result.files_indexed} indexed, "
                f"{result.files_skipped} skipped, "
                f"{result.files_failed} failed\n"
                f"Nodes: {result.nodes_created}, Edges: {result.edges_created}"
            )

            if result.errors:
                self.results.edge_cases.append(
                    f"memoria indexing had {len(result.errors)} errors: {result.errors[:3]}"
                )

            self.results.add_test(TestResult(
                name="Index memoria",
                passed=passed,
                duration_ms=duration,
                details=details,
                error=None if passed else f"Failed files: {result.files_failed}",
            ))

            # Record finding
            self.results.findings.append(
                f"memoria: {result.nodes_created} nodes, {result.edges_created} edges "
                f"in {duration/1000:.2f}s"
            )

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            self.results.add_test(TestResult(
                name="Index memoria",
                passed=False,
                duration_ms=duration,
                error=str(e),
            ))

    def _test_find_callers_memoria(self) -> None:
        """Test find_callers on memoria."""
        # Try to find callers of key functions
        test_symbols = ["remember", "search", "context", "store"]

        for symbol in test_symbols:
            start = time.perf_counter()
            try:
                callers = self.client.find_callers(symbol, self.memoria_path)
                duration = (time.perf_counter() - start) * 1000

                if callers:
                    details = f"Found {len(callers)} callers"
                    for caller in callers[:3]:
                        loc = caller.location
                        rel_path = Path(loc.file_path).relative_to(self.memoria_path)
                        details += f"\n  - {caller.name} at {rel_path}:{loc.start_line}"

                    self.results.add_test(TestResult(
                        name=f"find_callers('{symbol}')",
                        passed=duration < 100,
                        duration_ms=duration,
                        details=details,
                    ))
                else:
                    self.results.add_test(TestResult(
                        name=f"find_callers('{symbol}')",
                        passed=True,  # No callers is valid
                        duration_ms=duration,
                        details="No callers found (may be external API)",
                    ))

            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                self.results.add_test(TestResult(
                    name=f"find_callers('{symbol}')",
                    passed=False,
                    duration_ms=duration,
                    error=str(e),
                ))

    def _test_find_references_memoria(self) -> None:
        """Test find_references on memoria."""
        # Try common symbols
        test_symbols = ["MemoriaClient", "Memory", "store"]

        for symbol in test_symbols:
            start = time.perf_counter()
            try:
                refs = self.client.find_references(symbol, self.memoria_path)
                duration = (time.perf_counter() - start) * 1000

                details = f"Found {len(refs)} references"
                if refs:
                    for ref in refs[:3]:
                        loc = ref.location
                        rel_path = Path(loc.file_path).relative_to(self.memoria_path)
                        details += f"\n  - {ref.name} ({ref.kind.value}) at {rel_path}:{loc.start_line}"

                self.results.add_test(TestResult(
                    name=f"find_references('{symbol}')",
                    passed=duration < 100,
                    duration_ms=duration,
                    details=details,
                ))

            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                self.results.add_test(TestResult(
                    name=f"find_references('{symbol}')",
                    passed=False,
                    duration_ms=duration,
                    error=str(e),
                ))

    def _test_stats_memoria(self) -> None:
        """Get and validate stats for memoria."""
        start = time.perf_counter()
        try:
            stats = self.client.get_stats(self.memoria_path)
            duration = (time.perf_counter() - start) * 1000

            details = (
                f"Files: {stats.total_files}\n"
                f"Nodes: {stats.total_nodes}\n"
                f"Edges: {stats.total_edges}\n"
                f"Nodes by kind: {stats.nodes_by_kind}\n"
                f"Edges by kind: {stats.edges_by_kind}"
            )

            self.results.add_test(TestResult(
                name="Get memoria stats",
                passed=stats.total_nodes > 0 and duration < 100,
                duration_ms=duration,
                details=details,
            ))

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            self.results.add_test(TestResult(
                name="Get memoria stats",
                passed=False,
                duration_ms=duration,
                error=str(e),
            ))

    def _test_index_gateway(self) -> None:
        """Test indexing gateway-mcp (scale test)."""
        if not self.gateway_path.exists():
            self.results.add_test(TestResult(
                name="Index gateway-mcp",
                passed=False,
                duration_ms=0,
                error=f"Project not found: {self.gateway_path}",
            ))
            return

        files_indexed = []

        def progress(current: int, total: int, path: str) -> None:
            files_indexed.append(path)
            if current % 20 == 0 or current == total:
                print(f"       [{current}/{total}] {Path(path).name}")

        start = time.perf_counter()
        try:
            result = self.client.index_repo(
                self.gateway_path,
                force=True,
                progress_callback=progress,
            )
            duration = (time.perf_counter() - start) * 1000

            passed = result.files_failed == 0 and duration < 30000
            details = (
                f"Files: {result.files_indexed} indexed, "
                f"{result.files_skipped} skipped, "
                f"{result.files_failed} failed\n"
                f"Nodes: {result.nodes_created}, Edges: {result.edges_created}"
            )

            if result.errors:
                self.results.edge_cases.append(
                    f"gateway-mcp indexing had {len(result.errors)} errors: {result.errors[:3]}"
                )

            self.results.add_test(TestResult(
                name="Index gateway-mcp",
                passed=passed,
                duration_ms=duration,
                details=details,
                error=None if passed else f"Failed files: {result.files_failed}",
            ))

            # Record finding
            self.results.findings.append(
                f"gateway-mcp: {result.nodes_created} nodes, {result.edges_created} edges "
                f"in {duration/1000:.2f}s"
            )

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            self.results.add_test(TestResult(
                name="Index gateway-mcp",
                passed=False,
                duration_ms=duration,
                error=str(e),
            ))

    def _test_queries_gateway(self) -> None:
        """Test queries on gateway-mcp."""
        # Try gateway-specific symbols
        test_symbols = ["call", "describe", "GatewayServer"]

        for symbol in test_symbols:
            start = time.perf_counter()
            try:
                callers = self.client.find_callers(symbol, self.gateway_path)
                duration = (time.perf_counter() - start) * 1000

                details = f"Found {len(callers)} callers"
                if callers:
                    for caller in callers[:3]:
                        loc = caller.location
                        try:
                            rel_path = Path(loc.file_path).relative_to(self.gateway_path)
                        except ValueError:
                            rel_path = Path(loc.file_path).name
                        details += f"\n  - {caller.name} at {rel_path}:{loc.start_line}"

                self.results.add_test(TestResult(
                    name=f"gateway find_callers('{symbol}')",
                    passed=duration < 100,
                    duration_ms=duration,
                    details=details,
                ))

            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                self.results.add_test(TestResult(
                    name=f"gateway find_callers('{symbol}')",
                    passed=False,
                    duration_ms=duration,
                    error=str(e),
                ))

    def _print_summary(self) -> None:
        """Print test summary."""
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        print(f"\nTests: {self.results.passed} passed, {self.results.failed} failed")

        if self.results.findings:
            print("\nFindings:")
            for finding in self.results.findings:
                print(f"  - {finding}")

        if self.results.edge_cases:
            print("\nEdge Cases Discovered:")
            for edge_case in self.results.edge_cases:
                print(f"  - {edge_case}")

        if self.results.missing_for_phase2:
            print("\nMissing for Phase 2:")
            for item in self.results.missing_for_phase2:
                print(f"  - {item}")

        # Overall assessment
        print("\n" + "-" * 70)
        if self.results.failed == 0:
            print("SPIKE SUCCESSFUL - Ready to proceed to Phase 2")
        else:
            print(f"SPIKE NEEDS ATTENTION - {self.results.failed} tests failed")
        print("-" * 70)


def main():
    """Run the spike test."""
    spike = E2ESpike()
    results = spike.run()
    sys.exit(0 if results.failed == 0 else 1)


if __name__ == "__main__":
    main()
