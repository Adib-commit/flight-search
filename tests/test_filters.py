from __future__ import annotations

import json
from pathlib import Path

from app.filters import apply_filters, prune_unreasonable
from app.models import Itinerary, Segment
from app.transform import transform_offers

FIX = Path(__file__).parent / "fixtures" / "jfk_cdg.json"


def _load():
    return transform_offers(json.loads(FIX.read_text()))


def test_direct_only():
    out = apply_filters(_load(), max_connections=0, include_codes=[], exclude_codes=[])
    assert {i.id for i in out} == {"1"}


def test_exclude_carrier():
    out = apply_filters(
        _load(), max_connections=None, include_codes=[], exclude_codes=["FR"]
    )
    assert "2" not in {i.id for i in out}
    assert {"1", "3"} == {i.id for i in out}


def test_include_carrier():
    out = apply_filters(
        _load(), max_connections=None, include_codes=["DL"], exclude_codes=[]
    )
    assert {i.id for i in out} == {"3"}


def test_no_filter_keeps_all():
    out = apply_filters(_load(), max_connections=None, include_codes=[], exclude_codes=[])
    assert len(out) == 3


def test_max_price():
    out = apply_filters(
        _load(), max_connections=None, include_codes=[], exclude_codes=[], max_price=500
    )
    # only id2 (420) and id3 (510 > 500 -> excluded) ... 420 only
    assert {i.id for i in out} == {"2"}


def _itin(id_, dur_min, layover_min):
    seg = Segment("XX", "1", "AAA", "BBB", "", "", dur_min)
    return Itinerary(
        id=id_, price_total=100.0, currency="USD", carriers=["XX"],
        stops_count=1, total_duration_min=dur_min, layover_min=layover_min,
        segments=[seg],
    )


def test_prune_drops_absurd_duration_and_layover():
    items = [
        _itin("fast", 180, 0),       # 3h baseline
        _itin("ok", 360, 120),       # 6h, 2h layover — reasonable
        _itin("long", 2400, 60),     # 40h trip — absurd
        _itin("overnight", 600, 900),  # 15h layover — absurd
        _itin("a", 200, 0), _itin("b", 220, 0),  # padding so len > 5
    ]
    kept = {i.id for i in prune_unreasonable(items)}
    assert "long" not in kept
    assert "overnight" not in kept
    assert "fast" in kept and "ok" in kept


def test_prune_keeps_small_sets_untouched():
    items = [_itin("a", 5000, 5000), _itin("b", 100, 0)]
    assert len(prune_unreasonable(items)) == 2  # <=5 -> untouched
