"""Explicit stdlib-only Linux suite; no backend dependencies or real user service.

Run from a source checkout with: python -I -S tools/check_deck_compatibility.py
The exact interpreter version is printed; skipped contracts fail this CI gate.
"""
import os
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'test_deck', 'test_deck_discovery', 'test_deck_metadata', 'test_deck_doctor',
    'test_deck_install_recovery', 'test_deck_package', 'test_deck_acceptance',
    'test_watch', 'test_belmont',
)


def main():
    if sys.platform != 'linux' or sys.version_info < (3, 10):
        print('This compatibility gate requires Linux and Python 3.10 or later.')
        return 1
    print('Companion contracts: Python ' + platform.python_version() + ' / Linux', flush=True)
    # Explicit paths allow -I -S: do not depend on site-packages or PYTHONPATH.
    sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
    os.chdir(ROOT)
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print('Compatibility gate incomplete: skipped tests are not accepted.')
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
