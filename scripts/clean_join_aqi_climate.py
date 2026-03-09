#!/usr/bin/env python3
"""Clean and join EPA county AQI 2020 data with NOAA climate normals data.

Join strategy implemented here:
- AQI data is county-level (state/county).
- Climate normals archive is station-level and does not include county/FIPS.
- Therefore this script aggregates climate metrics to the state level and joins
  counties to their state's climate aggregates.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

AQI_NUMERIC_COLUMNS = [
    "Year",
    "Days with AQI",
    "Good Days",
    "Moderate Days",
    "Unhealthy for Sensitive Groups Days",
    "Unhealthy Days",
    "Very Unhealthy Days",
    "Hazardous Days",
    "Max AQI",
    "90th Percentile AQI",
    "Median AQI",
    "Days CO",
    "Days NO2",
    "Days Ozone",
    "Days PM2.5",
    "Days PM10",
]

CLIMATE_METRICS = [
    "ANN-TAVG-NORMAL",
    "ANN-TMIN-NORMAL",
    "ANN-TMAX-NORMAL",
    "ANN-PRCP-NORMAL",
]

# USPS state/territory abbreviations.
ABBR_TO_STATE = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District Of Columbia",
    "AS": "American Samoa",
    "GU": "Guam",
    "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico",
    "VI": "Virgin Islands",
}


def normalize_name(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def parse_int(value: str) -> Optional[int]:
    value = value.strip()
    if value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_float(value: str) -> Optional[float]:
    value = value.strip()
    if value == "":
        return None
    try:
        f = float(value)
    except ValueError:
        return None
    # NOAA missing sentinel in this dataset.
    if f <= -9990:
        return None
    return f


def read_aqi_from_zip(aqi_zip: Path) -> List[Dict[str, object]]:
    with zipfile.ZipFile(aqi_zip) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV files found in {aqi_zip}")

        with zf.open(csv_names[0]) as f:
            text_stream = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            reader = csv.DictReader(text_stream)
            rows: List[Dict[str, object]] = []

            for row in reader:
                cleaned: Dict[str, object] = {
                    "State": (row.get("State") or "").strip(),
                    "County": (row.get("County") or "").strip(),
                }

                for col in AQI_NUMERIC_COLUMNS:
                    cleaned[col] = parse_int(row.get(col, ""))

                rows.append(cleaned)

    return rows


def extract_state_abbr_from_station_name(name: str) -> Optional[str]:
    # Typical form: "CITY NAME, ST US" or "..., PR RQ"
    if not name:
        return None

    tail = name.split(",")[-1].strip().upper()
    parts = tail.split()
    if not parts:
        return None

    # Heuristic: state-like token is often second-to-last when country is present.
    candidates: List[str] = []
    if len(parts) >= 2:
        candidates.append(parts[-2])
    candidates.append(parts[-1])

    for c in candidates:
        if re.fullmatch(r"[A-Z]{2}", c) and c in ABBR_TO_STATE:
            return c

    return None


def iter_station_rows_from_tar(tar_path: Path) -> Iterable[Dict[str, str]]:
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf:
            if not member.isfile() or not member.name.lower().endswith(".csv"):
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                continue

            text_stream = io.TextIOWrapper(extracted, encoding="utf-8", errors="replace", newline="")
            reader = csv.DictReader(text_stream)
            first_row = next(reader, None)
            if first_row is not None:
                yield first_row


def aggregate_state_climate(climate_tar: Path) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    station_count_by_state: Dict[str, int] = defaultdict(int)

    for row in iter_station_rows_from_tar(climate_tar):
        abbr = extract_state_abbr_from_station_name((row.get("NAME") or "").strip())
        if not abbr:
            continue

        station_count_by_state[abbr] += 1
        for metric in CLIMATE_METRICS:
            value = parse_float(row.get(metric, ""))
            if value is None:
                continue
            totals[abbr][metric] += value
            counts[abbr][metric] += 1

    state_rows: List[Dict[str, object]] = []
    for abbr in sorted(station_count_by_state):
        state_name = ABBR_TO_STATE.get(abbr, abbr)
        out: Dict[str, object] = {
            "state_abbr": abbr,
            "state_name": state_name,
            "stations_used": station_count_by_state[abbr],
        }
        for metric in CLIMATE_METRICS:
            n = counts[abbr].get(metric, 0)
            out[metric] = round(totals[abbr][metric] / n, 4) if n else None
            out[f"{metric}_n"] = n
        state_rows.append(out)

    return state_rows, dict(station_count_by_state)


def join_county_to_state_climate(
    aqi_rows: List[Dict[str, object]],
    state_climate_rows: List[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    state_lookup = {normalize_name(str(r["state_name"])): r for r in state_climate_rows}

    joined: List[Dict[str, object]] = []
    unmatched_states = set()
    matched = 0

    for aqi in aqi_rows:
        key = normalize_name(str(aqi.get("State", "")))
        climate = state_lookup.get(key)

        out = dict(aqi)
        if climate:
            matched += 1
            out["climate_state_abbr"] = climate["state_abbr"]
            out["climate_stations_used"] = climate["stations_used"]
            for metric in CLIMATE_METRICS:
                out[f"state_{metric}"] = climate[metric]
        else:
            unmatched_states.add(str(aqi.get("State", "")))
            out["climate_state_abbr"] = None
            out["climate_stations_used"] = None
            for metric in CLIMATE_METRICS:
                out[f"state_{metric}"] = None

        joined.append(out)

    report = {
        "aqi_rows": len(aqi_rows),
        "joined_rows": len(joined),
        "rows_with_climate_match": matched,
        "rows_without_climate_match": len(joined) - matched,
        "distinct_unmatched_states": sorted(s for s in unmatched_states if s),
    }

    return joined, report


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and join AQI and climate normals datasets")
    parser.add_argument(
        "--aqi-zip",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/annual_aqi_by_county_2020.zip"),
        help="Path to annual_aqi_by_county_2020.zip",
    )
    parser.add_argument(
        "--climate-tar",
        type=Path,
        default=Path(
            "/Users/saichimbili/Downloads/us-climate-normals_2006-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz"
        ),
        help="Path to NOAA climate normals tar.gz",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/aqi_climate_outputs"),
        help="Output directory",
    )
    args = parser.parse_args()

    aqi_rows = read_aqi_from_zip(args.aqi_zip)
    state_climate_rows, _ = aggregate_state_climate(args.climate_tar)
    joined_rows, join_report = join_county_to_state_climate(aqi_rows, state_climate_rows)

    aqi_out = args.out_dir / "cleaned_aqi_2020.csv"
    climate_out = args.out_dir / "cleaned_climate_state_annual.csv"
    joined_out = args.out_dir / "joined_aqi_county_with_state_climate_2020.csv"
    report_out = args.out_dir / "join_report.json"

    write_csv(aqi_out, aqi_rows)
    write_csv(climate_out, state_climate_rows)
    write_csv(joined_out, joined_rows)
    report_out.write_text(json.dumps(join_report, indent=2), encoding="utf-8")

    print("Wrote:")
    print(f"- {aqi_out}")
    print(f"- {climate_out}")
    print(f"- {joined_out}")
    print(f"- {report_out}")
    print("Join report:")
    print(json.dumps(join_report, indent=2))


if __name__ == "__main__":
    main()
