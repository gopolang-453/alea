"""TEST 07 - versioned model files.
BEFORE (v2.3.1): everything saved to alea_model.json, so any version overwrote any other.
AFTER (v2.4): alea_model_<version>.json; a file from another version is refused unless explicitly allowed."""
import _paths, os, json, tempfile, hashlib
import alea_predictor_v2_4_1 as a
from _common import make
old = _paths.optional_import("alea_predictor_v2_3_1")

def sha(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()
df, *_ = make(11, n_matches=500)
pn = a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True); T = pn["teams"]
with tempfile.TemporaryDirectory() as d:
    cwd = os.getcwd(); os.chdir(d)
    try:
        if old is not None:                                   # a v2.3.1 model sitting in the folder, old-style
            po = old.fit_model(df, xi=0.0018, reg=1.0, verbose=False); old.save_model(po)
            assert os.path.exists("alea_model.json"); h_old = sha("alea_model.json")
        path = a.save_model(pn)
        print("v2.4 default file:", path)
        assert os.path.basename(path) == "alea_model_alea-dc-v2.4.1.json" and not os.path.exists(path + ".tmp")
        if old is not None:
            assert sha("alea_model.json") == h_old
            print("v2.3.1's alea_model.json is byte-identical after saving v2.4: nothing overwritten")
        q = a.load_model()                                    # default = this version's file
        assert a.predict(q, T[0], T[1])["p_home_win"] == a.predict(pn, T[0], T[1])["p_home_win"]
        assert q["data_sha256"] == pn["data_sha256"] and len(q["data_sha256"]) == 16
        # a file written by another version is refused
        other = dict(pn, model_version="alea-dc-v2.4"); fp = a.save_model(other, directory=".")
        assert os.path.basename(fp) == "alea_model_alea-dc-v2.4.json"
        for call in (lambda: a.load_model(fp), lambda: a.load_model(fp, expected_version="alea-dc-v2.4.1")):
            try: call(); raise SystemExit("FAIL: loaded a different version")
            except a.ModelVersionError as e: msg = str(e)
        print("loading another version's file ->", msg[:80], "...")
        assert a.load_model(fp, allow_version_mismatch=True)["model_version"] == "alea-dc-v2.4"
        # a corrupted / invalid model is refused on load
        bad = dict(pn, rho=0.29, home_adv=pn["home_adv"] + 3.0)       # rho no longer valid for every pairing
        with open("alea_model_alea-dc-v2.4.1.json", "w") as f: json.dump(bad, f)
        try: a.load_model(); raise SystemExit("FAIL: invalid model loaded")
        except RuntimeError: print("invalid (mathematically broken) model file refused on load")
        with open("alea_model_alea-dc-v2.4.1.json", "w") as f: json.dump({"teams": []}, f)
        try: a.load_model(); raise SystemExit("FAIL")
        except ValueError: pass
    finally:
        os.chdir(cwd)
print("PASS")
