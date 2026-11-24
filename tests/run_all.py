"""Runs every test file in this folder, prints a PASS/FAIL line as each one finishes, and writes the full
output of every test to ../TEST_RESULTS.txt.
    cd tests && python run_all.py
Needs: numpy pandas scipy requests (no internet). pytest is needed for the pytest-style Stage files.
Takes ~10-15 minutes (tests 09, 12, 13, 14 do many model fits).

Two kinds of file live here:
  * script-style v2.4.1 tests (test_01 .. test_15) that run their checks at import / under __main__;
  * pytest-style Stage tests that only *define* test_ functions.
Running a pytest-style file with plain `python file.py` executes nothing and exits 0, which earlier
made this runner report PASS for tests that never ran. pytest-style files are therefore run with
`python -m pytest`, and the repository root is put on PYTHONPATH so `import stages...` works."""
import glob, os, re, subprocess, sys, time, platform
from datetime import datetime
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here)
root = os.path.dirname(here)
log_path = os.path.join(root, "TEST_RESULTS.txt")
env = dict(os.environ)
env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")


def is_pytest_style(path):
    """True when the file defines test functions but has no script entry point."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    defines_tests = re.search(r"^def test_\w+\(", text, flags=re.M) is not None
    has_main = "__main__" in text
    return defines_tests and not has_main


results = []
with open(log_path, "w", encoding="utf-8") as log:
    log.write(f"ALEA test run  {datetime.now().isoformat(timespec='seconds')}  python {platform.python_version()}\n")
    for f in sorted(glob.glob("test_*.py")):
        if is_pytest_style(f):
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f]
            kind = "pytest"
        else:
            cmd = [sys.executable, f]
            kind = "script"
        t = time.time(); r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=here)
        ok = r.returncode == 0; secs = time.time() - t; results.append((f, ok, secs))
        log.write(f"\n{'=' * 78}\n{f}   [{kind}]   {'PASS' if ok else 'FAIL'}   {secs:.1f}s\n{'=' * 78}\n{r.stdout}\n{r.stderr if not ok else ''}")
        log.flush()
        print(f"{'PASS' if ok else 'FAIL'}  {f:48s} [{kind:6s}] {secs:6.1f}s", flush=True)
    summary = "\n" + "=" * 60 + f"\n{sum(ok for _, ok, _ in results)}/{len(results)} test files passed\n"
    log.write(summary)
print(summary, flush=True)
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
