from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field


class FlightDates(BaseModel):
    departure: date
    ret: date | None = Field(default=None, alias="return")

    model_config = {"populate_by_name": True}


class AirlineFilters(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    origin: str
    destination: str
    flight_dates: FlightDates
    traveler_count: int = 1
    max_connections: int | None = Field(
        default=None,
        ge=0,
        description="Max number of connections per direction. None = unlimited, 0 = direct only.",
    )
    airline_filters: AirlineFilters = Field(default_factory=AirlineFilters)
    max_price: float | None = Field(default=None, gt=0)


# ---- score breakdown ----

class ScoreBreakdown(BaseModel):
    """Per-dimension contribution to the ValueScore (lower = better value)."""
    price_component: float
    duration_component: float
    stops_component: float
    layover_component: float
    layover_quality_penalty: float   # risky / overnight / excessive penalties minus ideal bonus
    total: float


# ---- internal normalized structures ----

@dataclass
class Segment:
    carrier_code: str
    flight_number: str
    origin: str
    destination: str
    departure_at: str
    arrival_at: str
    duration_min: int
    origin_name: str = ""        # e.g. "Ben Gurion, Tel Aviv"
    destination_name: str = ""   # e.g. "Cluj International, Cluj-Napoca"
    direction: str = ""          # "outbound" | "inbound"
    layover_after_min: int = 0   # layover to next segment in same direction (0 = last/none)
    note: str = ""               # display caveat, e.g. day-min fare with unknown exact flight


@dataclass
class Itinerary:
    id: str
    price_total: float           # per-person fare (all calculations are per 1 person)
    currency: str
    carriers: list[str]          # unique IATA carrier codes across segments
    stops_count: int             # total stops across the whole trip (all directions)
    total_duration_min: int      # incl. layovers
    max_stops_per_dir: int = -1  # max stops in any single direction; -1 = fall back to stops_count
    layover_min: int = 0         # total time waiting between segments
    booking_url: str = ""        # deep-link to booking page
    segments: list[Segment] = field(default_factory=list)
    score: float | None = None           # filled by scoring engine
    score_breakdown: "ScoreBreakdown | None" = None  # per-dimension breakdown
    price_per_person: float = 0.0        # per-traveler fare; 0 until pax pricing applied


# ---- response ----

class SegmentOut(BaseModel):
    carrier: str
    carrier_name: str
    flight_number: str
    origin: str
    origin_name: str = ""
    destination: str
    destination_name: str = ""
    departure_at: str
    arrival_at: str
    duration_min: int
    direction: str = ""
    layover_after_min: int = 0
    note: str = ""


class ItineraryOut(BaseModel):
    id: str
    price_total: float           # per-person fare
    price_per_person: float = 0.0
    currency: str
    carriers: list[str]
    carrier_names: list[str]
    stops_count: int
    total_duration_min: int
    layover_min: int = 0
    booking_url: str = ""
    score: float | None = None
    score_breakdown: ScoreBreakdown | None = None   # per-dimension ValueScore breakdown
    segments: list[SegmentOut]


class SearchResponse(BaseModel):
    best_value: list[ItineraryOut]   # top 3 by score
    cheapest: ItineraryOut | None
    fastest: ItineraryOut | None
    options: list[ItineraryOut]      # all considered (sorted by score) for charting
    total_considered: int
    markdown: str
    split_via: str | None = None     # detected via airport for frontend to show spinner
    notice: str | None = None        # explanation when filters removed all results (200, not 404)


# ---- multi-day stopover (open-jaw) ----

class StopoverLegRequest(BaseModel):
    origin: str
    destination: str
    date: str   # YYYY-MM-DD departure date for this individual leg


class StopoverRequest(BaseModel):
    legs: list[StopoverLegRequest]   # 2 legs (one-way) or 4 legs (round-trip with stopover)
    traveler_count: int = 1
    max_connections: int | None = Field(default=None, ge=0)
    airline_filters: AirlineFilters = Field(default_factory=AirlineFilters)
    max_price: float | None = Field(default=None, gt=0)   # per-leg cap


class StopoverLegResult(BaseModel):
    label: str           # "TLV → OTP"
    date: str
    options: list[ItineraryOut]   # top 3 for this leg (cheapest first)
    cheapest_price: float
    currency: str
    error: str = ""


class StopoverResponse(BaseModel):
    legs: list[StopoverLegResult]
    total_price: float           # sum of cheapest per leg
    currency: str
