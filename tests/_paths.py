"""Makes the model files importable from the tests folder: the package root (v2.4 + value engine v0.2)
and ../baseline (older versions used for the BEFORE/AFTER comparisons). $ALEA_DIR is also searched."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.environ.get("ALEA_DIR"), os.path.join(ROOT, "baseline"), ROOT, HERE):
    if p and p not in sys.path:
        sys.path.insert(0, p)

def optional_import(name):
    """Import a module if its file exists, else None (older versions are only needed for BEFORE comparisons)."""
    try:
        return __import__(name)
    except ImportError:
        return None
