"""Installs the required packages automatically when they are missing.

Imported first by app.py, so 'ModuleNotFoundError: No module named flask' cannot happen:
the first run installs Flask into whatever Python interpreter is running the project.
"""
import importlib.util
import subprocess
import sys

REQUIRED = [("flask", "Flask>=2.2")]


def _pip(*args):
    return subprocess.call([sys.executable, "-m", "pip", "install", *args])


def ensure():
    missing = [pip_name for module, pip_name in REQUIRED if importlib.util.find_spec(module) is None]
    if not missing:
        return
    print("\n  Installing required packages: " + ", ".join(missing) + " (first run only)...\n")
    code = _pip(*missing)
    if code != 0:                       # e.g. no permission for system Python -> install for this user
        code = _pip("--user", *missing)
    if code != 0:                       # pip itself missing in this interpreter? bootstrap it, retry
        subprocess.call([sys.executable, "-m", "ensurepip", "--upgrade"])
        code = _pip(*missing)
    if code != 0:
        print("\n  [ERROR] Could not install automatically. Please run this in the PyCharm Terminal tab:\n"
              f"      \"{sys.executable}\" -m pip install -r requirements.txt\n"
              "  (needs an internet connection), then run the project again.\n")
        sys.exit(1)
    importlib.invalidate_caches()
    print("\n  Packages installed.\n")


ensure()
