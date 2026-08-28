from __future__ import annotations

import unittest

from stock_watch_worker.sec_fundamentals import extract_fundamentals


def _entry(
    value: float,
    *,
    start: str | None = None,
    end: str,
    filed: str,
    accession: str,
    form: str = "10-K",
) -> dict[str, object]:
    result: dict[str, object] = {
        "val": value,
        "end": end,
        "filed": filed,
        "accn": accession,
        "form": form,
    }
    if start:
        result["start"] = start
    return result


def _fact(entries: list[dict[str, object]], unit: str = "USD") -> dict[str, object]:
    return {"units": {unit: entries}}


def _company_facts() -> dict[str, object]:
    annual = {
        "old": dict(start="2024-01-01", end="2024-12-31", filed="2025-02-01", accession="a-2024"),
        "latest": dict(start="2025-01-01", end="2025-12-31", filed="2026-02-01", accession="a-2025"),
        "future": dict(start="2026-01-01", end="2026-12-31", filed="2027-02-01", accession="a-2026"),
    }
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _fact(
                    [
                        _entry(1_000, **annual["old"]),
                        _entry(1_200, **annual["latest"]),
                        _entry(9_999, **annual["future"]),
                    ]
                ),
                "NetIncomeLoss": _fact([_entry(120, **annual["latest"])]),
                "NetCashProvidedByUsedInOperatingActivities": _fact(
                    [_entry(180, **annual["latest"])]
                ),
                "PaymentsToAcquirePropertyPlantAndEquipment": _fact(
                    [_entry(50, **annual["latest"])]
                ),
                "EarningsPerShareDiluted": _fact(
                    [_entry(5, **annual["latest"])], "USD/shares"
                ),
                "Assets": _fact(
                    [_entry(1_000, end="2025-12-31", filed="2026-02-01", accession="i-assets")]
                ),
                "Liabilities": _fact(
                    [_entry(600, end="2025-12-31", filed="2026-02-01", accession="i-liabilities")]
                ),
                "StockholdersEquity": _fact(
                    [_entry(400, end="2025-12-31", filed="2026-02-01", accession="i-equity")]
                ),
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": _fact(
                    [_entry(100, end="2025-12-31", filed="2026-02-01", accession="i-shares")],
                    "shares",
                )
            },
        }
    }


class SecFundamentalTests(unittest.TestCase):
    def test_extracts_only_facts_filed_by_cutoff(self) -> None:
        result = extract_fundamentals(
            _company_facts(), as_of="2026-08-20T20:00:00Z", price=100
        )

        inputs = result.inputs
        self.assertAlmostEqual(inputs.revenue_growth or 0, 0.20)
        self.assertAlmostEqual(inputs.net_margin or 0, 0.10)
        self.assertAlmostEqual(inputs.free_cash_flow_margin or 0, 130 / 1_200)
        self.assertAlmostEqual(inputs.debt_to_equity or 0, 1.5)
        self.assertAlmostEqual(inputs.price_to_earnings or 0, 20.0)
        self.assertAlmostEqual(inputs.free_cash_flow_yield or 0, 0.013)
        self.assertEqual(result.raw["annual_revenue"], 1_200)
        self.assertNotIn("a-2026", result.accessions)
        self.assertEqual(inputs.as_of, "2026-02-01")

    def test_early_cutoff_does_not_use_later_annual_filing(self) -> None:
        result = extract_fundamentals(
            _company_facts(), as_of="2025-06-01", price=100
        )

        self.assertEqual(result.raw["annual_revenue"], 1_000)
        self.assertIsNone(result.inputs.revenue_growth)
        self.assertIsNone(result.inputs.net_margin)
        self.assertNotIn("a-2025", result.accessions)

    def test_missing_company_facts_produces_explicitly_missing_inputs(self) -> None:
        result = extract_fundamentals({}, as_of="2026-08-20", price=100)

        self.assertIsNone(result.inputs.revenue_growth)
        self.assertIsNone(result.inputs.price_to_earnings)
        self.assertEqual(result.accessions, ())

    def test_rejects_invalid_price_or_cutoff(self) -> None:
        with self.assertRaisesRegex(ValueError, "price"):
            extract_fundamentals({}, as_of="2026-08-20", price=0)
        with self.assertRaises(ValueError):
            extract_fundamentals({}, as_of="not-a-date", price=100)


if __name__ == "__main__":
    unittest.main()
