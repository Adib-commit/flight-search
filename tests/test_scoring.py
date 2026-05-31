import json
from pathlib import Path

from app.config import Settings
from app.output import build_response
from app.scoring import score_itineraries
from app.transform import transform_offers

FIX = Path(__file__).parent / "fixtures" / "jfk_cdg.json"


def _settings():
    # New min-max model: all four metrics scaled 0..1, weights sum to 1.0.
    return Settings(
        weight_price=0.35, weight_duration=0.30, weight_stops=0.20, weight_layover=0.15
    )


def test_score_formula():
    its = transform_offers(json.loads(FIX.read_text()))
    scored = score_itineraries(its, _settings())
    s = _settings()

    prices = [i.price_total for i in scored]
    durs = [i.total_duration_min for i in scored]
    stops = [i.stops_count for i in scored]
    lays = [i.layover_min for i in scored]
    lo_p, hi_p = min(prices), max(prices)
    lo_d, hi_d = min(durs), max(durs)
    lo_s, hi_s = min(stops), max(stops)
    lo_l, hi_l = min(lays), max(lays)

    def mm(v, lo, hi):
        return 0.0 if hi <= lo else (v - lo) / (hi - lo)

    direct = next(i for i in scored if i.id == "1")
    expected = (
        s.weight_price * mm(direct.price_total, lo_p, hi_p)
        + s.weight_duration * mm(direct.total_duration_min, lo_d, hi_d)
        + s.weight_stops * mm(direct.stops_count, lo_s, hi_s)
        + s.weight_layover * mm(direct.layover_min, lo_l, hi_l)
    )
    assert abs(direct.score - expected) < 1e-6


def test_direct_beats_connections():
    its = transform_offers(json.loads(FIX.read_text()))
    scored = score_itineraries(its, _settings())
    best = min(scored, key=lambda i: i.score)
    # The direct, zero-layover flight should win best value.
    assert best.id == "1"


def test_build_response_buckets():
    its = transform_offers(json.loads(FIX.read_text()))
    scored = score_itineraries(its, _settings())
    resp = build_response(scored)
    assert resp.cheapest.id == "2"   # 420 = lowest price
    assert resp.fastest.id == "1"    # 450 min = shortest
    assert len(resp.best_value) == 3
    assert resp.total_considered == 3
    assert "Best Value" in resp.markdown
