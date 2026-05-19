"""Master test runner. Runs all five suites and prints a dashboard.

Usage:
  python scripts/run_tests.py              # all
  python scripts/run_tests.py --skip chat  # skip slow live-Gemini suite
  python scripts/run_tests.py only=visual  # run only one
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.common import main_report
from tests import test_data, test_api, test_tools, test_chat, test_visual


SUITES = {
    "data":   ("Data integrity",     test_data.run),
    "api":    ("API endpoints",      test_api.run),
    "tools":  ("Tools (direct)",     test_tools.run),
    "chat":   ("Chat scenarios",     test_chat.run),
    "visual": ("Visual + clicks",    test_visual.run),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", action="append", default=[], help="suite key to skip (data/api/tools/chat/visual)")
    ap.add_argument("--only", action="append", default=[], help="run only this suite key")
    args = ap.parse_args()

    keys = list(SUITES.keys())
    if args.only:
        keys = [k for k in keys if k in args.only]
    for sk in args.skip:
        if sk in keys:
            keys.remove(sk)

    reports = []
    for k in keys:
        title, fn = SUITES[k]
        print(f"\n══ {title} ══")
        try:
            rep = fn()
        except Exception as e:
            from tests.common import Report
            rep = Report(title)
            rep.fail("suite crashed", repr(e))
        rep.print_summary()
        reports.append(rep)

    sys.exit(main_report(*reports))


if __name__ == "__main__":
    main()
