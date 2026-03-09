#!/usr/bin/env python3
"""Combine county emissions summary with AQI + climate table.

Input tables:
- /Users/saichimbili/Downloads/point_forreport_outputs/county_emissions_summary_joined.csv
- /Users/saichimbili/Downloads/aqi_climate_outputs/joined_aqi_county_with_state_climate_2020.csv

Output:
- /Users/saichimbili/Downloads/final_combined_emissions_aqi_climate_2020.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, Tuple


def norm_state(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def norm_county(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"\bCOUNTY\b|\bPARISH\b|\bBOROUGH\b|\bCENSUS AREA\b|\bMUNICIPIO\b", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine emissions, AQI, and climate data")
    parser.add_argument(
        "--emissions",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/point_forreport_outputs/county_emissions_summary_joined.csv"),
    )
    parser.add_argument(
        "--aqi-climate",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/aqi_climate_outputs/joined_aqi_county_with_state_climate_2020.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/final_combined_emissions_aqi_climate_2020.csv"),
    )
    args = parser.parse_args()

    emissions_by_key: Dict[Tuple[str, str], Dict[str, str]] = {}
    with args.emissions.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (norm_state(row.get("STATE_NAME", "")), norm_county(row.get("COUNTY_NAME", "")))
            emissions_by_key[key] = row

    combined_rows = []
    matched = 0
    with args.aqi_climate.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (norm_state(row.get("State", "")), norm_county(row.get("County", "")))
            em = emissions_by_key.get(key)

            out = dict(row)
            if em:
                matched += 1
                out.update(
                    {
                        "em_FIPS": em.get("FIPS", ""),
                        "em_EPA_REGION": em.get("EPA_REGION", ""),
                        "em_TOTAL_EMISSIONS_TON": em.get("TOTAL_EMISSIONS_TON", ""),
                        "em_POLLUTANT_COUNT": em.get("POLLUTANT_COUNT", ""),
                        "em_FACILITY_COUNT": em.get("FACILITY_COUNT", ""),
                        "em_TOP_POLLUTANT": em.get("TOP_POLLUTANT", ""),
                        "em_TOP_POLLUTANT_EMISSIONS_TON": em.get("TOP_POLLUTANT_EMISSIONS_TON", ""),
                        "em_TOP_POLLUTANT_SHARE_PCT": em.get("TOP_POLLUTANT_SHARE_PCT", ""),
                        "em_TOP_FACILITY_TYPE": em.get("TOP_FACILITY_TYPE", ""),
                        "em_TOP_FACILITY_TYPE_EMISSIONS_TON": em.get("TOP_FACILITY_TYPE_EMISSIONS_TON", ""),
                        "em_TOP_FACILITY": em.get("TOP_FACILITY", ""),
                        "em_TOP_FACILITY_EMISSIONS_TON": em.get("TOP_FACILITY_EMISSIONS_TON", ""),
                    }
                )
            else:
                out.update(
                    {
                        "em_FIPS": "",
                        "em_EPA_REGION": "",
                        "em_TOTAL_EMISSIONS_TON": "",
                        "em_POLLUTANT_COUNT": "",
                        "em_FACILITY_COUNT": "",
                        "em_TOP_POLLUTANT": "",
                        "em_TOP_POLLUTANT_EMISSIONS_TON": "",
                        "em_TOP_POLLUTANT_SHARE_PCT": "",
                        "em_TOP_FACILITY_TYPE": "",
                        "em_TOP_FACILITY_TYPE_EMISSIONS_TON": "",
                        "em_TOP_FACILITY": "",
                        "em_TOP_FACILITY_EMISSIONS_TON": "",
                    }
                )

            combined_rows.append(out)

    if not combined_rows:
        raise RuntimeError("No combined rows produced")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(combined_rows[0].keys()))
        writer.writeheader()
        writer.writerows(combined_rows)

    print(f"Wrote: {args.output}")
    print(f"rows: {len(combined_rows)}")
    print(f"matched rows with emissions: {matched}")
    print(f"unmatched rows: {len(combined_rows)-matched}")


if __name__ == "__main__":
    main()
