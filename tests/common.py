"""Shared helpers for the test suite."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "app" / "data"
BACKEND_URL = "http://127.0.0.1:8000"


@dataclass
class Report:
    name: str
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.passed.append(msg)

    def fail(self, msg: str, detail: str = "") -> None:
        self.failed.append((msg, detail))

    @property
    def status(self) -> str:
        return "PASS" if not self.failed else "FAIL"

    def print_summary(self) -> None:
        total = len(self.passed) + len(self.failed)
        print(f"  {self.status:>4}  {self.name:30s}  {len(self.passed)}/{total} checks")
        for m, d in self.failed:
            print(f"     × {m}")
            if d:
                for line in d.splitlines():
                    print(f"        {line}")


@contextmanager
def section(name: str):
    print(f"\n══ {name} ══")
    t = time.perf_counter()
    yield
    dt = time.perf_counter() - t
    print(f"   ({dt:.2f}s)")


def assert_or_fail(report: Report, cond: bool, ok_msg: str, fail_msg: str | None = None, detail: str = "") -> None:
    if cond:
        report.ok(ok_msg)
    else:
        report.fail(fail_msg or ok_msg, detail)


def main_report(*reports: Report) -> int:
    print("\n" + "═" * 56)
    print("SUMMARY")
    for r in reports:
        r.print_summary()
    failed_total = sum(len(r.failed) for r in reports)
    print("═" * 56)
    print(f"  {'OVERALL':>4}  {'PASS' if not failed_total else 'FAIL'}  {failed_total} failures")
    return 1 if failed_total else 0
