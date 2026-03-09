#!/usr/bin/env python3
"""Clean and join related fields in point_forreport.csv.

Outputs:
- point_forreport_cleaned.csv: cleaned row-level records.
- county_emissions_summary_joined.csv: county-level table joined with top pollutant,
  top facility type, and top facility emissions context.
- state_emissions_summary.csv: state-level emissions rollup.
- pollutant_emissions_summary.csv: pollutant-level emissions rollup.
- point_forreport_report.json: run stats and quality checks.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

INPUT_COLUMNS = [
    "FIPS",
    "POLLUTANT",
    "EMISSIONS_POINT_TON",
    "Latest_Site_Name",
    "FACILITY_TYPE_DESCRIPTION",
    "Latest_Street_Address",
    "NAICS_DESCRIPTION",
    "EPA_REGION",
    "STATE_COUNTY",
    "STATE_NAME",
]


def clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def parse_state_county(state_county: str) -> Tuple[str, str]:
    # Expected pattern: "CO - Lincoln"
    parts = state_county.split(" - ", 1)
    if len(parts) == 2:
        return clean_text(parts[0]), clean_text(parts[1])
    return "", clean_text(state_county)


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and join related fields in point_forreport.csv")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/point_forreport.csv"),
        help="Path to point_forreport.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/point_forreport_outputs"),
        help="Output directory",
    )
    parser.add_argument(
        "--write-cleaned-rows",
        action="store_true",
        help="Write full cleaned row-level CSV (large file). Disabled by default.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    cleaned_path = args.out_dir / "point_forreport_cleaned.csv"
    county_summary_path = args.out_dir / "county_emissions_summary_joined.csv"
    state_summary_path = args.out_dir / "state_emissions_summary.csv"
    pollutant_summary_path = args.out_dir / "pollutant_emissions_summary.csv"
    report_path = args.out_dir / "point_forreport_report.json"

    county_dims: Dict[str, Dict[str, str]] = {}
    county_total = defaultdict(float)
    county_pollutant = defaultdict(float)          # (fips, pollutant) -> emissions
    county_facility_type = defaultdict(float)      # (fips, facility type) -> emissions
    county_facility = defaultdict(float)           # (fips, facility name) -> emissions
    county_pollutant_count = defaultdict(set)
    county_facility_count = defaultdict(set)

    state_total = defaultdict(float)
    pollutant_total = defaultdict(float)

    row_count = 0
    invalid_fips_count = 0
    dim_conflicts = 0

    cleaned_fieldnames = [
        "FIPS",
        "STATE_NAME",
        "STATE_ABBR",
        "COUNTY_NAME",
        "STATE_COUNTY",
        "EPA_REGION",
        "POLLUTANT",
        "EMISSIONS_POINT_TON",
        "Latest_Site_Name",
        "FACILITY_TYPE_DESCRIPTION",
        "NAICS_DESCRIPTION",
        "Latest_Street_Address",
    ]

    with args.input.open("r", encoding="utf-8", errors="replace", newline="") as f_in:
        reader = csv.DictReader(f_in)
        if reader.fieldnames and reader.fieldnames[0].startswith("\ufeff"):
            reader.fieldnames[0] = reader.fieldnames[0].lstrip("\ufeff")

        writer = None
        f_out = None
        if args.write_cleaned_rows:
            f_out = cleaned_path.open("w", encoding="utf-8", newline="")
            writer = csv.DictWriter(f_out, fieldnames=cleaned_fieldnames)
            writer.writeheader()

        try:
            for row in reader:
                row_count += 1

                raw_fips = clean_text(row.get("FIPS", ""))
                fips = raw_fips.zfill(5) if raw_fips.isdigit() else raw_fips
                if len(fips) != 5 or not fips.isdigit():
                    invalid_fips_count += 1

                pollutant = clean_text(row.get("POLLUTANT", ""))
                site_name = clean_text(row.get("Latest_Site_Name", ""))
                facility_type = clean_text(row.get("FACILITY_TYPE_DESCRIPTION", ""))
                naics_desc = clean_text(row.get("NAICS_DESCRIPTION", ""))
                street = clean_text(row.get("Latest_Street_Address", ""))
                epa_region = clean_text(row.get("EPA_REGION", ""))
                state_county = clean_text(row.get("STATE_COUNTY", ""))
                state_name = clean_text(row.get("STATE_NAME", ""))
                state_abbr, county_name = parse_state_county(state_county)

                emissions = float((row.get("EMISSIONS_POINT_TON") or "0").strip())

                if writer is not None:
                    cleaned_row = {
                        "FIPS": fips,
                        "STATE_NAME": state_name,
                        "STATE_ABBR": state_abbr,
                        "COUNTY_NAME": county_name,
                        "STATE_COUNTY": state_county,
                        "EPA_REGION": epa_region,
                        "POLLUTANT": pollutant,
                        "EMISSIONS_POINT_TON": round(emissions, 8),
                        "Latest_Site_Name": site_name,
                        "FACILITY_TYPE_DESCRIPTION": facility_type,
                        "NAICS_DESCRIPTION": naics_desc,
                        "Latest_Street_Address": street,
                    }
                    writer.writerow(cleaned_row)

                # County dimension consistency checks.
                dim = county_dims.get(fips)
                if dim is None:
                    county_dims[fips] = {
                        "FIPS": fips,
                        "STATE_NAME": state_name,
                        "STATE_ABBR": state_abbr,
                        "COUNTY_NAME": county_name,
                        "STATE_COUNTY": state_county,
                        "EPA_REGION": epa_region,
                    }
                else:
                    if (
                        dim["STATE_NAME"] != state_name
                        or dim["COUNTY_NAME"] != county_name
                        or dim["STATE_COUNTY"] != state_county
                    ):
                        dim_conflicts += 1

                # Aggregations used for the joined summary.
                county_total[fips] += emissions
                county_pollutant[(fips, pollutant)] += emissions
                county_facility_type[(fips, facility_type)] += emissions
                county_facility[(fips, site_name)] += emissions
                county_pollutant_count[fips].add(pollutant)
                county_facility_count[fips].add(site_name)

                state_total[state_name] += emissions
                pollutant_total[pollutant] += emissions
        finally:
            if f_out is not None:
                f_out.close()

    # Compute top related dimensions for each county.
    top_pollutant_by_county: Dict[str, Tuple[str, float]] = {}
    for (fips, pollutant), emissions in county_pollutant.items():
        best = top_pollutant_by_county.get(fips)
        if best is None or emissions > best[1]:
            top_pollutant_by_county[fips] = (pollutant, emissions)

    top_facility_type_by_county: Dict[str, Tuple[str, float]] = {}
    for (fips, facility_type), emissions in county_facility_type.items():
        best = top_facility_type_by_county.get(fips)
        if best is None or emissions > best[1]:
            top_facility_type_by_county[fips] = (facility_type, emissions)

    top_facility_by_county: Dict[str, Tuple[str, float]] = {}
    for (fips, site_name), emissions in county_facility.items():
        best = top_facility_by_county.get(fips)
        if best is None or emissions > best[1]:
            top_facility_by_county[fips] = (site_name, emissions)

    county_summary_rows: List[Dict[str, object]] = []
    for fips in sorted(county_dims):
        dim = county_dims[fips]
        total = county_total[fips]
        top_pollutant_name, top_pollutant_em = top_pollutant_by_county.get(fips, ("", 0.0))
        top_ft_name, top_ft_em = top_facility_type_by_county.get(fips, ("", 0.0))
        top_site_name, top_site_em = top_facility_by_county.get(fips, ("", 0.0))

        county_summary_rows.append(
            {
                **dim,
                "TOTAL_EMISSIONS_TON": round(total, 6),
                "POLLUTANT_COUNT": len(county_pollutant_count[fips]),
                "FACILITY_COUNT": len(county_facility_count[fips]),
                "TOP_POLLUTANT": top_pollutant_name,
                "TOP_POLLUTANT_EMISSIONS_TON": round(top_pollutant_em, 6),
                "TOP_POLLUTANT_SHARE_PCT": round((top_pollutant_em / total * 100.0) if total else 0.0, 2),
                "TOP_FACILITY_TYPE": top_ft_name,
                "TOP_FACILITY_TYPE_EMISSIONS_TON": round(top_ft_em, 6),
                "TOP_FACILITY": top_site_name,
                "TOP_FACILITY_EMISSIONS_TON": round(top_site_em, 6),
            }
        )

    # State and pollutant summaries.
    state_rows = [
        {
            "STATE_NAME": s,
            "TOTAL_EMISSIONS_TON": round(em, 6),
        }
        for s, em in sorted(state_total.items(), key=lambda x: x[1], reverse=True)
    ]

    pollutant_rows = [
        {
            "POLLUTANT": p,
            "TOTAL_EMISSIONS_TON": round(em, 6),
        }
        for p, em in sorted(pollutant_total.items(), key=lambda x: x[1], reverse=True)
    ]

    write_csv(county_summary_path, county_summary_rows)
    write_csv(state_summary_path, state_rows)
    write_csv(pollutant_summary_path, pollutant_rows)

    national_total = sum(county_total.values())
    top_county = max(county_summary_rows, key=lambda r: float(r["TOTAL_EMISSIONS_TON"])) if county_summary_rows else None
    top_state = state_rows[0] if state_rows else None
    top_pollutant = pollutant_rows[0] if pollutant_rows else None

    report = {
        "rows_processed": row_count,
        "unique_counties": len(county_dims),
        "unique_states": len(state_total),
        "unique_pollutants": len(pollutant_total),
        "invalid_fips_rows": invalid_fips_count,
        "county_dimension_conflicts": dim_conflicts,
        "national_total_emissions_ton": round(national_total, 6),
        "top_state": top_state,
        "top_pollutant": top_pollutant,
        "top_county": top_county,
        "files_written": {
            "cleaned_rows": str(cleaned_path) if args.write_cleaned_rows else None,
            "county_summary_joined": str(county_summary_path),
            "state_summary": str(state_summary_path),
            "pollutant_summary": str(pollutant_summary_path),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Wrote outputs to:", args.out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
