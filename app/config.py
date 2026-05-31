from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration loaded from environment / .env."""

    # Data provider:
    #   "rapidapi-kiwi" - Kiwi.com Cheap Flights via RapidAPI (real LCC fares)
    #   "rapidapi"      - Sky-Scrapper / Skyscanner via RapidAPI
    #   "kiwi"          - Kiwi Tequila direct
    #   "amadeus"       - Amadeus Self-Service
    #   "mock"          - offline sample data, no key
    provider: str = "rapidapi-kiwi"

    # RapidAPI (https://rapidapi.com) — used when PROVIDER=rapidapi*
    rapidapi_key: str = ""
    rapidapi_host: str = "sky-scrapper.p.rapidapi.com"
    rapidapi_market: str = "US"
    rapidapi_locale: str = "en-US"
    kiwi_rapidapi_host: str = "kiwi-com-cheap-flights.p.rapidapi.com"
    kayak_rapidapi_host: str = "kayak-api.p.rapidapi.com"
    skyscanner_rapidapi_host: str = "skyscanner-flights-travel-api.p.rapidapi.com"

    amadeus_api_key: str = ""
    amadeus_api_secret: str = ""
    amadeus_env: str = "test"  # "test" or "production"

    # Kiwi.com Tequila API (https://tequila.kiwi.com)
    kiwi_api_key: str = ""
    kiwi_base_url: str = "https://api.tequila.kiwi.com"

    # "Best value" = low cost + short total time + few stops/direct + short layovers.
    # All four are min-max normalized, so weights are true proportions (sum 1.0).
    weight_price: float = 0.25
    weight_duration: float = 0.30
    weight_stops: float = 0.30
    weight_layover: float = 0.15

    currency: str = "USD"

    # Logging: level for root logger; all logs go to console + logs/app.log
    log_level: str = "INFO"

    # Admin error notifications: email admins when ERROR/CRITICAL is logged.
    admin_error_alerts: bool = True
    # Extra recipients (comma-separated); admins from the user store are always included.
    admin_error_emails: str = ""
    # Min minutes between identical error emails (anti-spam throttle).
    error_alert_cooldown_min: int = 10

    # SMTP email settings (for price-alert notifications)
    smtp_host: str = ""           # e.g. smtp.gmail.com
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "flight-alerts@example.com"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def amadeus_base_url(self) -> str:
        if self.amadeus_env == "production":
            return "https://api.amadeus.com"
        return "https://test.api.amadeus.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
