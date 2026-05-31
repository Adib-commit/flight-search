"""Best-Value scoring engine.

Formula (lower score = better value):

    ValueScore = Wp*norm_price
               + Wd*norm_duration
               + Ws*norm_stops
               + Wl*norm_layover
               + layover_quality_penalty

All base terms are min-max normalised to a 0..1 range so the configured
weights are true proportions.

Layover quality penalties (additive, per itinerary):
  - Risky short connection (<60 min): +RISKY_PENALTY per segment
  - Overnight / excessive layover   (>6 h): +OVERNIGHT_PENALTY per segment
    + EXCESS_FACTOR for every full hour beyond 6 h
  - Ideal window (90–180 min): −IDEAL_BONUS per segment (small reward)
"""
from __future__ import annotations

from .config import Settings
from .models import Itinerary, ScoreBreakdown


# ── layover quality thresholds & penalties ─────────────────────────────────
_RISKY_MAX_MIN: int = 60        # < 60 min connection = risky
_IDEAL_MIN_MIN: int = 90        # ideal window lower bound
_IDEAL_MAX_MIN: int = 180       # ideal window upper bound
_OVERNIGHT_MIN: int = 360       # ≥ 6 h = overnight / excessive

_RISKY_PENALTY: float = 0.30    # added to score per risky connection
_OVERNIGHT_PENALTY: float = 0.40  # base added per overnight/excessive layover
_EXCESS_FACTOR: float = 0.04    # extra per hour beyond 6 h
_IDEAL_BONUS: float = 0.05      # subtracted per ideal-window layover


def _layover_quality_penalty(itinerary: Itinerary) -> float:
    """Return total quality penalty from per-segment layover analysis."""
    total = 0.0
    for seg in itinerary.segments:
        mins = seg.layover_after_min
        if mins <= 0:
            continue  # last segment in direction / no layover
        if mins < _RISKY_MAX_MIN:
            total += _RISKY_PENALTY
        elif mins >= _OVERNIGHT_MIN:
            total += _OVERNIGHT_PENALTY
            excess_hours = (mins - _OVERNIGHT_MIN) / 60.0
            total += _EXCESS_FACTOR * excess_hours
        elif _IDEAL_MIN_MIN <= mins <= _IDEAL_MAX_MIN:
            total -= _IDEAL_BONUS
    return total


def score_itineraries(
    itineraries: list[Itinerary], settings: Settings
) -> list[Itinerary]:
    """Compute weighted ValueScore for each itinerary.  Lower = better value."""
    if not itineraries:
        return itineraries

    # ── normalisation anchors ──────────────────────────────────────────────
    min_price = min((it.price_total for it in itineraries if it.price_total > 0), default=1.0) or 1.0
    max_price = max((it.price_total for it in itineraries if it.price_total > 0), default=min_price) or 1.0

    min_dur = min((it.total_duration_min for it in itineraries if it.total_duration_min > 0), default=1) or 1
    max_dur = max((it.total_duration_min for it in itineraries if it.total_duration_min > 0), default=min_dur) or 1

    max_stops = max((it.stops_count for it in itineraries), default=0)
    max_layover = max((it.layover_min for it in itineraries), default=0)

    price_range = max(max_price - min_price, 1.0)
    dur_range = max(max_dur - min_dur, 1)

    for it in itineraries:
        # ── base components (0..1) ─────────────────────────────────────────
        norm_price = (it.price_total - min_price) / price_range if it.price_total > 0 else 0.0
        norm_dur = ((it.total_duration_min - min_dur) / dur_range
                    if it.total_duration_min > 0 else 0.0)
        norm_stops = (it.stops_count / max_stops) if max_stops > 0 else 0.0
        norm_layover = (it.layover_min / max_layover) if max_layover > 0 else 0.0

        # ── layover quality penalty ────────────────────────────────────────
        lq_penalty = _layover_quality_penalty(it)

        # ── weighted sum ──────────────────────────────────────────────────
        base = (
            settings.weight_price * norm_price
            + settings.weight_duration * norm_dur
            + settings.weight_stops * norm_stops
            + settings.weight_layover * norm_layover
        )
        it.score = base + lq_penalty

        it.score_breakdown = ScoreBreakdown(
            price_component=round(settings.weight_price * norm_price, 4),
            duration_component=round(settings.weight_duration * norm_dur, 4),
            stops_component=round(settings.weight_stops * norm_stops, 4),
            layover_component=round(settings.weight_layover * norm_layover, 4),
            layover_quality_penalty=round(lq_penalty, 4),
            total=round(it.score, 4),
        )

    return itineraries
