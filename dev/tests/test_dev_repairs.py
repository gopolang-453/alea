"""Development-copy checks. Does not import or modify v2.4.1."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import alea_predictor_dev as a
import alea_value_engine_v0_2_1 as v


def _frame(rows):
    df = pd.DataFrame(rows, columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def test_reg0_refuses_a_team_with_no_goals():
    # One match, Burnley scored 0. The unpenalised attack MLE does not exist.
    rows = []
    clubs = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Newcastle", "Brighton"]
    # a small complete league so the other teams have goals
    day = pd.Timestamp("2023-08-01")
    k = 0
    for i, h in enumerate(clubs):
        for aw in clubs[i + 1:]:
            rows.append((str((day + pd.Timedelta(days=k)).date()), h, aw, 1 + (k % 3), k % 2))
            k += 1
    rows.append(("2023-08-20", "Burnley", "Arsenal", 0, 3))
    df = _frame(rows)
    try:
        a.fit_model(df, xi=0.0, reg=0.0, verbose=False, as_of_date="2023-08-21")
    except ValueError as exc:
        assert "unbounded" in str(exc)
    else:
        raise SystemExit("reg=0 should have been refused")
    params = a.fit_model(df, xi=0.0, reg=1.0, verbose=False, as_of_date="2023-08-21")
    p = a._predict_outcome_probs(params, "Burnley", "Chelsea", allow_new_teams=True)
    assert abs(p.sum() - 1) < 1e-12
    assert p.min() > 0.01
    print("PASS reg=0 refused; reg=1 probability", np.round(p, 4), "min", round(float(p.min()), 4))


def test_alias_and_save_load(tmp=Path("/tmp/alea_dev_model.json")):
    assert a._team_name("Man United") == "Manchester United"
    assert a._team_name("Man City") == "Manchester City"
    rows = []
    clubs = ["Arsenal", "Chelsea", "Liverpool", "Everton"]
    day = pd.Timestamp("2024-01-01")
    k = 0
    for i, h in enumerate(clubs):
        for aw in clubs:
            if h == aw:
                continue
            rows.append((str((day + pd.Timedelta(days=k)).date()), h, aw, 1 + (k % 2), k % 2))
            k += 1
    df = _frame(rows)
    params = a.fit_model(df, xi=0.0, reg=1.0, verbose=False, as_of_date="2024-03-01")
    a.save_model(params, tmp)
    loaded = a.load_model(tmp)
    assert loaded["model_version"] == "alea-dc-dev"
    p1 = a._predict_outcome_probs(params, "Arsenal", "Chelsea")
    p2 = a._predict_outcome_probs(loaded, "Arsenal", "Chelsea")
    assert np.allclose(p1, p2)
    pred = a.predict(loaded, "Arsenal", "Chelsea")
    mk = pred["markets"]
    assert abs(mk["home"] + mk["draw"] + mk["away"] - 1) < 1e-12
    ev = v.analyse_market(
        {"home": mk["home"], "draw": mk["draw"], "away": mk["away"]},
        {"home": 2.10, "draw": 3.40, "away": 3.60},
    )
    assert ev["staking_enabled"] is False
    assert abs(sum(ev["outcomes"][k]["market_probability_proportional_devig"] for k in ev["outcomes"]) - 1) < 1e-12
    print("PASS save/load, 1X2 sums to 1, value engine rejects nothing on a valid market")


def test_extreme_team_strength_refused():
    # A tiny 4-team league where one team wins every match by the maximum
    # plausible margin (15-0), repeated, with near-zero regularisation.
    # The unpenalised MLE pushes that team's attack strength past the
    # 3 log-point sanity cap (~20x the league scoring rate), which must be
    # refused with reg this low, and must fit cleanly once reg is sane.
    clubs = ["Titan", "A", "B", "C"]
    rows, day, k = [], pd.Timestamp("2023-08-01"), 0
    for _ in range(6):
        for i, h in enumerate(clubs):
            for aw in clubs[i + 1:]:
                if h == "Titan":
                    hg, ag = 15, 0
                elif aw == "Titan":
                    hg, ag = 0, 15
                else:
                    hg, ag = 1 + (k % 2), k % 3
                rows.append((str((day + pd.Timedelta(days=k)).date()), h, aw, hg, ag))
                k += 1
    df = _frame(rows)

    for reg in (0.0001, 0.001, 0.01):
        try:
            a.fit_model(df, xi=0.0, reg=reg, verbose=False, as_of_date="2025-01-01")
        except RuntimeError as exc:
            assert "3 log-points" in str(exc)
        else:
            raise SystemExit(f"reg={reg} should have tripped the team-strength sanity check")

    # Confirm the guard isn't just always-on: a sane reg fits normally.
    params = a.fit_model(df, xi=0.0, reg=0.1, verbose=False, as_of_date="2025-01-01")
    assert abs(params["attack"]["Titan"]) <= 3.0
    print("PASS extreme team strength refused at low reg; sane reg fits normally")


def test_invalid_input_refused():
    df = _frame([("2024-01-01", "Arsenal", "Arsenal", 1, 0)])
    try:
        a.fit_model(df, xi=0.0, reg=1.0, verbose=False, live=True)
    except Exception:
        print("PASS self-fixture refused")
    else:
        raise SystemExit("a team playing itself should be refused")


def test_shin_and_value_arithmetic():
    fair = a.shin_devig(2.10, 3.40, 3.50)
    s = fair["p_home"] + fair["p_draw"] + fair["p_away"]
    assert abs(s - 1) < 1e-12
    # 50% model at 2.10 is +5% expected return. The engine must say so, and must not stake.
    ev = v.analyse_market({"home": 0.50, "draw": 0.30, "away": 0.20},
                          {"home": 2.10, "draw": 3.40, "away": 4.50})
    assert abs(ev["outcomes"]["home"]["expected_net_return_per_unit"] - 0.05) < 1e-12
    try:
        v.analyse_market({"home": 0.5, "draw": 0.5}, {"home": 1.0, "draw": 2.0})
    except ValueError:
        pass
    else:
        raise SystemExit("odds of 1.00 should be refused")
    print("PASS Shin sums to 1 and value-engine EV is p*odds-1")


if __name__ == "__main__":
    test_reg0_refuses_a_team_with_no_goals()
    test_alias_and_save_load()
    test_extreme_team_strength_refused()
    test_invalid_input_refused()
    test_shin_and_value_arithmetic()
    print("ALL DEV CHECKS PASSED")
