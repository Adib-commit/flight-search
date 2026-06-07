from __future__ import annotations

from .airlines import code_to_name
from .models import Itinerary, ItineraryOut, SearchResponse, SegmentOut


def _fmt_dur(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


def to_out(it: Itinerary) -> ItineraryOut:
    return ItineraryOut(
        id=it.id,
        price_total=it.price_total,
        price_per_person=it.price_per_person or it.price_total,
        currency=it.currency,
        carriers=it.carriers,
        carrier_names=[code_to_name(c) for c in it.carriers],
        stops_count=it.stops_count,
        total_duration_min=it.total_duration_min,
        layover_min=it.layover_min,
        booking_url=it.booking_url,
        score=round(it.score, 4) if it.score is not None else None,
        score_breakdown=it.score_breakdown,
        segments=[
            SegmentOut(
                carrier=s.carrier_code,
                carrier_name=code_to_name(s.carrier_code),
                flight_number=s.flight_number,
                origin=s.origin,
                origin_name=s.origin_name,
                destination=s.destination,
                destination_name=s.destination_name,
                departure_at=s.departure_at,
                arrival_at=s.arrival_at,
                duration_min=s.duration_min,
                direction=s.direction,
                layover_after_min=s.layover_after_min,
                note=s.note,
            )
            for s in it.segments
        ],
    )


def _markdown_table(title: str, rows: list[Itinerary]) -> str:
    lines = [f"### {title}", "",
             "| # | Price | Airlines | Stops | Layover | Duration | Score |",
             "|---|-------|----------|-------|---------|----------|-------|"]
    for i, it in enumerate(rows, 1):
        names = ", ".join(code_to_name(c) for c in it.carriers)
        score = f"{it.score:.3f}" if it.score is not None else "-"
        lines.append(
            f"| {i} | {it.price_total:.2f} {it.currency} | {names} | "
            f"{it.stops_count} | {_fmt_dur(it.layover_min)} | "
            f"{_fmt_dur(it.total_duration_min)} | {score} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_response(scored: list[Itinerary]) -> SearchResponse:
    """Build top-3 best value, cheapest, fastest (spec §6)."""
    best = sorted(scored, key=lambda it: (it.score if it.score is not None else 1e9))
    top3 = best[:3]
    cheapest = min(scored, key=lambda it: it.price_total) if scored else None
    fastest = min(scored, key=lambda it: it.total_duration_min) if scored else None

    md_parts = [_markdown_table("Top 3 — Best Value", top3)]
    if cheapest:
        md_parts.append(_markdown_table("Cheapest", [cheapest]))
    if fastest:
        md_parts.append(_markdown_table("Fastest", [fastest]))

    return SearchResponse(
        best_value=[to_out(it) for it in top3],
        cheapest=to_out(cheapest) if cheapest else None,
        fastest=to_out(fastest) if fastest else None,
        options=[to_out(it) for it in best[:12]],   # for cost visualization
        total_considered=len(scored),
        markdown="\n".join(md_parts),
    )
