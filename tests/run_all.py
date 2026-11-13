"""Runs every test file in this folder, prints a PASS/FAIL line as each one finishes, and writes the full
output of every test to ../TEST_RESULTS.txt.
    cd tests && python run_all.py
Needs: numpy pandas scipy requests (no internet). Takes ~10-15 minutes (tests 09, 12, 13, 14 do many model fits)."""
import glob, os, subprocess, sys, time, platform
from datetime import datetime
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here)
log_path = os.path.join(os.path.dirname(here), "TEST_RESULTS.txt")
results = []
with open(log_path, "w", encoding="utf-8") as log:
    log.write(f"ALEA v2.4.1 test run  {datetime.now().isoformat(timespec='seconds')}  python {platform.python_version()}\n")
    for f in sorted(glob.glob("test_*.py")):
        t = time.time(); r = subprocess.run([sys.executable, f], capture_output=True, text=True)
        ok = r.returncode == 0; secs = time.time() - t; results.append((f, ok, secs))
        log.write(f"\n{'=' * 78}\n{f}   {'PASS' if ok else 'FAIL'}   {secs:.1f}s\n{'=' * 78}\n{r.stdout}\n{r.stderr if not ok else ''}")
        log.flush()
        print(f"{'PASS' if ok else 'FAIL'}  {f:48s} {secs:6.1f}s", flush=True)
    summary = "\n" + "=" * 60 + f"\n{sum(ok for _, ok, _ in results)}/{len(results)} test files passed\n"
    log.write(summary)
print(summary, flush=True)
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
