"""Conservative point-in-time extraction from SEC Company Facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from .features import FundamentalInputs


REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
NET_INCOME_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")
OPERATING_CASH_FLOW_CONCEPTS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_CONCEPTS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForAdditionsToPropertyPlantAndEquipment",
)
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
ASSET_CONCEPTS = ("Assets",)
LIABILITY_CONCEPTS = ("Liabilities",)
EQUITY_CONCEPTS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
SHARE_CONCEPTS = ("EntityCommonStockSharesOutstanding",)


@dataclass(frozen=True, slots=True)
class ExtractedFundamentals:
    inputs: FundamentalInputs
    raw: Mapping[str, float | str | None]
    accessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactPoint:
    value: float
    filed: str
    end: str
    accession: str | None
    start: str | None = None


def extract_fundamentals(
    company_facts: Mapping[str, Any],
    *,
    as_of: str,
    price: float,
) -> ExtractedFundamentals:
    """Extract annual quality/valuation inputs using only filings available by cutoff."""

    if price <= 0:
        raise ValueError("price must be positive")
    cutoff = as_of[:10]
    _parse_date(cutoff)

    revenue = _best_annual_series(company_facts, "us-gaap", REVENUE_CONCEPTS, "USD", cutoff)
    net_income = _best_annual_series(
        company_facts, "us-gaap", NET_INCOME_CONCEPTS, "USD", cutoff
    )
    operating_cash = _best_annual_series(
        company_facts, "us-gaap", OPERATING_CASH_FLOW_CONCEPTS, "USD", cutoff
    )
    capex = _best_annual_series(company_facts, "us-gaap", CAPEX_CONCEPTS, "USD", cutoff)
    eps = _best_annual_series(company_facts, "us-gaap", EPS_CONCEPTS, "USD/shares", cutoff)

    latest_revenue = revenue[-1] if revenue else None
    previous_revenue = revenue[-2] if len(revenue) >= 2 else None
    net_point = _point_for_end(net_income, latest_revenue.end if latest_revenue else None)
    cash_point = _point_for_end(operating_cash, latest_revenue.end if latest_revenue else None)
    capex_point = _point_for_end(capex, latest_revenue.end if latest_revenue else None)
    eps_point = _point_for_end(eps, latest_revenue.end if latest_revenue else None)

    assets = _latest_instant(company_facts, "us-gaap", ASSET_CONCEPTS, "USD", cutoff)
    liabilities = _latest_instant(
        company_facts, "us-gaap", LIABILITY_CONCEPTS, "USD", cutoff
    )
    equity = _latest_instant(company_facts, "us-gaap", EQUITY_CONCEPTS, "USD", cutoff)
    shares = _latest_instant(company_facts, "dei", SHARE_CONCEPTS, "shares", cutoff)

    revenue_growth = _safe_growth(latest_revenue, previous_revenue)
    net_margin = _safe_ratio(net_point, latest_revenue)
    free_cash_flow = (
        cash_point.value - abs(capex_point.value)
        if cash_point is not None and capex_point is not None
        else None
    )
    free_cash_flow_margin = (
        free_cash_flow / latest_revenue.value
        if free_cash_flow is not None and latest_revenue and latest_revenue.value != 0
        else None
    )
    debt_to_equity = (
        liabilities.value / equity.value
        if liabilities and equity and equity.value > 0
        else None
    )
    price_to_earnings = (
        price / eps_point.value if eps_point and eps_point.value > 0 else None
    )
    market_cap = price * shares.value if shares and shares.value > 0 else None
    free_cash_flow_yield = (
        free_cash_flow / market_cap
        if free_cash_flow is not None and market_cap and market_cap > 0
        else None
    )

    used_points = tuple(
        point
        for point in (
            latest_revenue,
            previous_revenue,
            net_point,
            cash_point,
            capex_point,
            eps_point,
            assets,
            liabilities,
            equity,
            shares,
        )
        if point is not None
    )
    data_as_of = max((point.filed for point in used_points), default=cutoff)
    accessions = tuple(
        sorted({point.accession for point in used_points if point.accession})
    )

    inputs = FundamentalInputs(
        as_of=data_as_of,
        revenue_growth=revenue_growth,
        net_margin=net_margin,
        free_cash_flow_margin=free_cash_flow_margin,
        debt_to_equity=debt_to_equity,
        price_to_earnings=price_to_earnings,
        free_cash_flow_yield=free_cash_flow_yield,
    )
    return ExtractedFundamentals(
        inputs=inputs,
        raw={
            "annual_revenue": latest_revenue.value if latest_revenue else None,
            "annual_net_income": net_point.value if net_point else None,
            "annual_operating_cash_flow": cash_point.value if cash_point else None,
            "annual_capex": capex_point.value if capex_point else None,
            "annual_free_cash_flow": free_cash_flow,
            "assets": assets.value if assets else None,
            "liabilities": liabilities.value if liabilities else None,
            "stockholders_equity": equity.value if equity else None,
            "shares_outstanding": shares.value if shares else None,
            "data_as_of": data_as_of,
        },
        accessions=accessions,
    )


def _best_annual_series(
    company_facts: Mapping[str, Any],
    namespace: str,
    concepts: Sequence[str],
    unit: str,
    cutoff: str,
) -> tuple[FactPoint, ...]:
    candidates = [
        _annual_series(company_facts, namespace, concept, unit, cutoff)
        for concept in concepts
    ]
    return max(candidates, key=lambda values: (len(values), values[-1].end if values else ""))


def _annual_series(
    company_facts: Mapping[str, Any],
    namespace: str,
    concept: str,
    unit: str,
    cutoff: str,
) -> tuple[FactPoint, ...]:
    entries = _unit_entries(company_facts, namespace, concept, unit)
    by_end: dict[str, FactPoint] = {}
    for entry in entries:
        if entry.get("form") != "10-K":
            continue
        filed = str(entry.get("filed", ""))
        start = str(entry.get("start", ""))
        end = str(entry.get("end", ""))
        if not filed or filed > cutoff or not start or not end:
            continue
        duration = (_parse_date(end) - _parse_date(start)).days
        if not 300 <= duration <= 430:
            continue
        point = _fact_point(entry, start=start)
        existing = by_end.get(end)
        if existing is None or point.filed > existing.filed:
            by_end[end] = point
    return tuple(by_end[end] for end in sorted(by_end))


def _latest_instant(
    company_facts: Mapping[str, Any],
    namespace: str,
    concepts: Sequence[str],
    unit: str,
    cutoff: str,
) -> FactPoint | None:
    points: list[FactPoint] = []
    for concept in concepts:
        for entry in _unit_entries(company_facts, namespace, concept, unit):
            if entry.get("form") not in {"10-K", "10-Q"}:
                continue
            filed = str(entry.get("filed", ""))
            end = str(entry.get("end", ""))
            if not filed or filed > cutoff or not end or end > cutoff:
                continue
            try:
                points.append(_fact_point(entry))
            except ValueError:
                continue
    return max(points, key=lambda point: (point.end, point.filed)) if points else None


def _unit_entries(
    company_facts: Mapping[str, Any],
    namespace: str,
    concept: str,
    unit: str,
) -> Iterable[Mapping[str, Any]]:
    facts = company_facts.get("facts")
    if not isinstance(facts, dict):
        return ()
    namespace_facts = facts.get(namespace)
    if not isinstance(namespace_facts, dict):
        return ()
    fact = namespace_facts.get(concept)
    if not isinstance(fact, dict):
        return ()
    units = fact.get("units")
    if not isinstance(units, dict):
        return ()
    entries = units.get(unit)
    return entries if isinstance(entries, list) else ()


def _fact_point(entry: Mapping[str, Any], start: str | None = None) -> FactPoint:
    value = float(entry["val"])
    filed = str(entry["filed"])
    end = str(entry["end"])
    return FactPoint(
        value=value,
        filed=filed,
        end=end,
        accession=str(entry["accn"]) if entry.get("accn") else None,
        start=start,
    )


def _point_for_end(
    points: Sequence[FactPoint], end: str | None
) -> FactPoint | None:
    if end is None:
        return points[-1] if points else None
    exact = [point for point in points if point.end == end]
    return exact[-1] if exact else None


def _safe_growth(latest: FactPoint | None, previous: FactPoint | None) -> float | None:
    if latest is None or previous is None or previous.value == 0:
        return None
    return latest.value / previous.value - 1.0


def _safe_ratio(numerator: FactPoint | None, denominator: FactPoint | None) -> float | None:
    if numerator is None or denominator is None or denominator.value == 0:
        return None
    return numerator.value / denominator.value


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)
