"""Non-crypto reference markets: gold, FX majors.

Why these exist
---------------
Every study on this platform so far has ended at the same wall: the strategies
find a small edge and the transaction costs eat it. Gold and the FX majors are
the cleanest available control for that claim, because they change one variable
at a time:

* **Cost.** A EUR/USD round trip costs roughly 0.02%. A crypto perpetual round
  trip costs roughly 0.12%. Same strategies, six times less friction.
* **Volatility.** Gold moves ~1% a day, altcoins ~8%. Different regime, same
  logic.

If a strategy is profitable on EUR/USD and negative on crypto, the problem is
cost, not the strategy. If it loses on both, the strategy has no edge anywhere.
That is a genuinely useful diagnostic, and it is the only reason these markets
are here.

What they are NOT
-----------------
Tradable. Binance has no EUR/USD or USD/JPY market, so the platform can never
place an order on them and they are flagged ``tradable=False``. The Risk Engine
rejects any signal on a non-tradable symbol before it can reach the Execution
Engine. Gold is the exception: Binance lists a real XAU/USDT perpetual.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.constants import StrEnum


class MarketKind(StrEnum):
    """What a market actually is, which decides how it may be used."""

    CRYPTO = "crypto"
    COMMODITY = "commodity"
    FOREX = "forex"


@dataclass(frozen=True, slots=True)
class ReferenceMarket:
    """A market that is not a Binance crypto perpetual."""

    symbol: str
    kind: MarketKind
    description: str
    #: Which history provider serves its candles.
    provider: str
    #: The identifier that provider uses.
    provider_symbol: str
    #: False means no order can ever be placed. Research only.
    tradable: bool
    #: When the market is open, in plain words.
    session: str
    #: Typical round-trip cost as a percentage, for the backtest cost model.
    typical_round_trip_cost_pct: float
    #: Timeframes the provider can actually serve, and how far back.
    history_limits: dict[str, str] = field(default_factory=dict)
    #: False when the feed carries no volume at all. Spot FX has no central
    #: exchange and therefore no consolidated volume, which silently disables
    #: every volume filter in the strategy library.
    has_volume: bool = True
    notes: str = ""


#: Yahoo caps intraday history hard: 60 days below one hour, two years at one
#: hour. Stating it here means the market browser can warn before a sweep is
#: built on 15 minute FX data that cannot support a conclusion.
_YAHOO_LIMITS = {
    "5m": "60 days",
    "15m": "60 days",
    "30m": "60 days",
    "1h": "730 days",
    "1d": "several years",
}

REFERENCE_MARKETS: dict[str, ReferenceMarket] = {
    "XAU/USDT": ReferenceMarket(
        symbol="XAU/USDT",
        kind=MarketKind.COMMODITY,
        description="Gold against the dollar, as a Binance perpetual",
        provider="binance",
        provider_symbol="XAU/USDT",
        tradable=True,
        session="24/7 - Binance runs this as a synthetic perpetual, not the spot gold session",
        typical_round_trip_cost_pct=0.12,
        history_limits={"all": "since 11 December 2025"},
        notes=(
            "A real Binance market with real Binance costs. Listed in December 2025, "
            "so there is under a year of history: enough to compare against crypto over "
            "the same window, not enough for a multi-year study."
        ),
    ),
    "PAXG/USDT": ReferenceMarket(
        symbol="PAXG/USDT",
        kind=MarketKind.COMMODITY,
        description="Pax Gold, a gold-backed token, against the dollar",
        provider="binance",
        provider_symbol="PAXG/USDT",
        tradable=True,
        session="24/7",
        typical_round_trip_cost_pct=0.12,
        history_limits={"all": "since 27 March 2025"},
        notes=(
            "Tracks the same underlying metal as XAU/USDT but trades as an ordinary "
            "crypto token, and has a longer history. Useful as a second gold sample."
        ),
    ),
    "EUR/USD": ReferenceMarket(
        symbol="EUR/USD",
        kind=MarketKind.FOREX,
        description="Euro against the US dollar",
        provider="yahoo",
        provider_symbol="EURUSD=X",
        tradable=False,
        session="Monday 22:00 to Friday 22:00 UTC. Closed at weekends.",
        typical_round_trip_cost_pct=0.02,
        history_limits=_YAHOO_LIMITS,
        has_volume=False,
        notes=(
            "Research only: Binance has no FX market, so no order can be placed here. "
            "The weekend close leaves gaps that every strategy in this platform reads "
            "as an ordinary bar, which is a real distortion, not a rounding error."
        ),
    ),
    "USD/JPY": ReferenceMarket(
        symbol="USD/JPY",
        kind=MarketKind.FOREX,
        description="US dollar against the Japanese yen",
        provider="yahoo",
        provider_symbol="JPY=X",
        tradable=False,
        session="Monday 22:00 to Friday 22:00 UTC. Closed at weekends.",
        typical_round_trip_cost_pct=0.02,
        history_limits=_YAHOO_LIMITS,
        has_volume=False,
        notes=(
            "Research only, same weekend-gap caveat as EUR/USD. Quoted as yen per "
            "dollar, so the number rises when the dollar strengthens."
        ),
    ),
}


def get(symbol: str) -> ReferenceMarket | None:
    """Look up a reference market, or None for an ordinary crypto symbol."""
    return REFERENCE_MARKETS.get(symbol.upper())


def is_reference(symbol: str) -> bool:
    return symbol.upper() in REFERENCE_MARKETS


def is_tradable(symbol: str) -> bool:
    """True unless the symbol is explicitly a research-only market.

    Unknown symbols are treated as tradable because they are ordinary Binance
    markets; only the entries above can turn this off.
    """
    market = REFERENCE_MARKETS.get(symbol.upper())
    return True if market is None else market.tradable


def externally_sourced() -> dict[str, ReferenceMarket]:
    """Reference markets whose candles do NOT come from Binance."""
    return {
        symbol: market
        for symbol, market in REFERENCE_MARKETS.items()
        if market.provider != "binance"
    }


def has_session_gaps(symbol: str) -> bool:
    """True when the market closes, so its candle stream is not continuous.

    This matters more than it looks. A downloader that treats "fewer candles
    than I asked for" as "there is no more data" is correct for a 24/7 crypto
    market and wrong for FX, where a week contains five sessions and two days of
    nothing. Getting it wrong silently truncates the history to the first page.
    """
    market = REFERENCE_MARKETS.get(symbol.upper())
    return market is not None and market.kind is MarketKind.FOREX


#: Strategies that cannot produce a single entry on a feed with no volume.
#:
#: Determined by running every strategy twice over the same prices, once with
#: volume and once with it zeroed, and keeping only those that went from trading
#: to silent. Six strategies *mention* volume; only this one is gated on it.
#: The others use it as one score component among several and still trade, they
#: just score that component at zero - worth knowing when reading an FX result,
#: but not a reason to discard it.
VOLUME_DEPENDENT_STRATEGIES: tuple[str, ...] = ("vwap_pullback",)

#: Strategies that read volume as one input among many. They still run without
#: it, with that component permanently scoring zero.
VOLUME_INFLUENCED_STRATEGIES: tuple[str, ...] = (
    "adaptive_momentum",
    "breakout_donchian",
    "keltner_trend",
    "mean_reversion",
    "volatility_breakout",
)


def has_volume(symbol: str) -> bool:
    """False when this market's feed carries no volume data."""
    market = REFERENCE_MARKETS.get(symbol.upper())
    return True if market is None else market.has_volume


def untestable_strategies(symbol: str) -> tuple[str, ...]:
    """Strategies that cannot produce a signal on this market at all.

    Returned so the caller can say "this one could not run here" instead of
    quietly reporting zero trades, which reads as a working strategy that found
    nothing rather than a strategy that never started.
    """
    return () if has_volume(symbol) else VOLUME_DEPENDENT_STRATEGIES


def degraded_strategies(symbol: str) -> tuple[str, ...]:
    """Strategies that still run here but with one scoring input missing."""
    return () if has_volume(symbol) else VOLUME_INFLUENCED_STRATEGIES


def kind_of(symbol: str) -> MarketKind:
    market = REFERENCE_MARKETS.get(symbol.upper())
    return market.kind if market else MarketKind.CRYPTO
