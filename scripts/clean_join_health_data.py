#!/usr/bin/env python3
"""Clean and join health datasets, then attach health context to the package final file.

Health inputs:
- Heat-related deaths: state-level, 2020.
- Air toxics cancer risk: county-pollutant level, 2019.

Outputs:
- cleaned individual health files
- county and state health summaries
- joined health state summary
- final combined air/climate/emissions/health file
- brief brainstorming notes for project checkpoint use
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean_text(value).upper())


def parse_float(value: str) -> Optional[float]:
    text = clean_text(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str) -> Optional[int]:
    text = clean_text(value)
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def read_csv_from_zip(zip_path: Path) -> Tuple[List[str], Iterable[Dict[str, str]]]:
    zf = zipfile.ZipFile(zip_path)
    csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if not csv_names:
        zf.close()
        raise ValueError(f"No CSV found in {zip_path}")

    file_obj = zf.open(csv_names[0])
    text_obj = io.TextIOWrapper(file_obj, encoding="utf-8", errors="replace", newline="")
    reader = csv.DictReader(text_obj)
    if reader.fieldnames and reader.fieldnames[0].startswith("\ufeff"):
        reader.fieldnames[0] = reader.fieldnames[0].lstrip("\ufeff")

    def iterator() -> Iterable[Dict[str, str]]:
        try:
            for row in reader:
                yield row
        finally:
            text_obj.close()
            file_obj.close()
            zf.close()

    return reader.fieldnames or [], iterator()


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_heat_rows(zip_path: Path) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, object]]]:
    _, rows = read_csv_from_zip(zip_path)
    cleaned_rows: List[Dict[str, object]] = []
    state_lookup: Dict[str, Dict[str, object]] = {}

    for row in rows:
        state_fips = clean_text(row.get("StateFIPS", "")).zfill(2)
        state_name = clean_text(row.get("State", ""))
        year = parse_int(row.get("Year", ""))
        raw_value = clean_text(row.get("Value", ""))
        data_comment = clean_text(row.get("Data Comment", ""))

        if raw_value.lower() == "suppressed":
            status = "suppressed"
            deaths = None
        else:
            status = "reported"
            deaths = parse_int(raw_value)

        cleaned = {
            "state_fips": state_fips,
            "state_name": state_name,
            "year": year,
            "heat_related_deaths": deaths,
            "heat_related_deaths_status": status,
            "data_comment": data_comment or None,
        }
        cleaned_rows.append(cleaned)
        state_lookup[normalize_name(state_name)] = cleaned

    return cleaned_rows, state_lookup


def build_air_toxics_rows(
    zip_path: Path,
) -> Tuple[
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    Dict[str, Dict[str, object]],
]:
    _, rows = read_csv_from_zip(zip_path)
    cleaned_rows: List[Dict[str, object]] = []

    county_dims: Dict[str, Dict[str, object]] = {}
    county_totals: Dict[str, float] = defaultdict(float)
    county_pollutant_totals: Dict[Tuple[str, str], float] = defaultdict(float)
    state_county_totals: Dict[str, List[float]] = defaultdict(list)
    state_top_county: Dict[str, Tuple[str, float]] = {}
    state_pollutant_totals: Dict[Tuple[str, str], float] = defaultdict(float)

    for row in rows:
        state_fips = clean_text(row.get("StateFIPS", "")).zfill(2)
        state_name = clean_text(row.get("State", ""))
        county_fips = clean_text(row.get("CountyFIPS", "")).zfill(5)
        county_name = clean_text(row.get("County", ""))
        year = parse_int(row.get("Year", ""))
        value = parse_float(row.get("Value", ""))
        data_comment = clean_text(row.get("Data Comment", ""))
        pollutant = clean_text(row.get("Pollutant", ""))
        pollutant = pollutant.replace("Pollutant:", "", 1).strip()

        cleaned = {
            "state_fips": state_fips,
            "state_name": state_name,
            "county_fips": county_fips,
            "county_name": county_name,
            "year": year,
            "pollutant": pollutant,
            "annual_avg_cancer_risk_per_million": value,
            "data_comment": data_comment or None,
        }
        cleaned_rows.append(cleaned)

        county_dims[county_fips] = {
            "state_fips": state_fips,
            "state_name": state_name,
            "county_fips": county_fips,
            "county_name": county_name,
            "year": year,
        }
        if value is None:
            continue
        county_totals[county_fips] += value
        county_pollutant_totals[(county_fips, pollutant)] += value
        state_pollutant_totals[(state_name, pollutant)] += value

    county_rows: List[Dict[str, object]] = []
    county_lookup: Dict[str, Dict[str, object]] = {}
    for county_fips, dim in sorted(county_dims.items()):
        total_risk = county_totals.get(county_fips, 0.0)
        county_pairs = [
            (pollutant, risk)
            for (fips, pollutant), risk in county_pollutant_totals.items()
            if fips == county_fips
        ]
        county_pairs.sort(key=lambda item: item[1], reverse=True)
        top_pollutant, top_risk = county_pairs[0] if county_pairs else ("", 0.0)

        county_row = {
            **dim,
            "county_total_cancer_risk_per_million": round(total_risk, 4),
            "pollutant_count": len(county_pairs),
            "top_pollutant": top_pollutant,
            "top_pollutant_risk_per_million": round(top_risk, 4),
        }
        county_rows.append(county_row)
        county_lookup[county_fips] = county_row
        state_county_totals[dim["state_name"]].append(total_risk)

        current_best = state_top_county.get(dim["state_name"])
        candidate_label = dim["county_name"]
        if current_best is None or total_risk > current_best[1]:
            state_top_county[dim["state_name"]] = (candidate_label, total_risk)

    state_rows: List[Dict[str, object]] = []
    for state_name, county_values in sorted(state_county_totals.items()):
        pollutant_pairs = [
            (pollutant, risk)
            for (state, pollutant), risk in state_pollutant_totals.items()
            if state == state_name
        ]
        pollutant_pairs.sort(key=lambda item: item[1], reverse=True)
        top_pollutant, top_pollutant_total = pollutant_pairs[0] if pollutant_pairs else ("", 0.0)
        top_county_name, top_county_risk = state_top_county.get(state_name, ("", 0.0))
        state_fips = ""
        year = None
        for county_row in county_rows:
            if county_row["state_name"] == state_name:
                state_fips = str(county_row["state_fips"])
                year = county_row["year"]
                break

        state_rows.append(
            {
                "state_fips": state_fips,
                "state_name": state_name,
                "air_toxics_year": year,
                "county_count_in_air_toxics": len(county_values),
                "mean_county_total_cancer_risk_per_million": round(sum(county_values) / len(county_values), 4),
                "max_county_total_cancer_risk_per_million": round(max(county_values), 4),
                "top_county_by_cancer_risk": top_county_name,
                "top_county_cancer_risk_per_million": round(top_county_risk, 4),
                "top_pollutant_statewide": top_pollutant,
                "top_pollutant_statewide_total_risk_per_million": round(top_pollutant_total, 4),
            }
        )

    return cleaned_rows, county_rows, state_rows, county_lookup


def join_health_state(
    heat_rows: List[Dict[str, object]],
    air_state_rows: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    heat_lookup = {normalize_name(str(row["state_name"])): row for row in heat_rows}
    air_lookup = {normalize_name(str(row["state_name"])): row for row in air_state_rows}
    all_keys = sorted(set(heat_lookup) | set(air_lookup))

    joined_rows: List[Dict[str, object]] = []
    for key in all_keys:
        heat = heat_lookup.get(key, {})
        air = air_lookup.get(key, {})
        joined_rows.append(
            {
                "state_fips": heat.get("state_fips") or air.get("state_fips"),
                "state_name": heat.get("state_name") or air.get("state_name"),
                "heat_deaths_year": heat.get("year"),
                "heat_related_deaths": heat.get("heat_related_deaths"),
                "heat_related_deaths_status": heat.get("heat_related_deaths_status"),
                "air_toxics_year": air.get("air_toxics_year"),
                "county_count_in_air_toxics": air.get("county_count_in_air_toxics"),
                "mean_county_total_cancer_risk_per_million": air.get(
                    "mean_county_total_cancer_risk_per_million"
                ),
                "max_county_total_cancer_risk_per_million": air.get(
                    "max_county_total_cancer_risk_per_million"
                ),
                "top_county_by_cancer_risk": air.get("top_county_by_cancer_risk"),
                "top_county_cancer_risk_per_million": air.get("top_county_cancer_risk_per_million"),
                "top_pollutant_statewide": air.get("top_pollutant_statewide"),
                "top_pollutant_statewide_total_risk_per_million": air.get(
                    "top_pollutant_statewide_total_risk_per_million"
                ),
            }
        )

    return joined_rows


def merge_with_existing_final(
    existing_final_path: Path,
    out_path: Path,
    county_lookup: Dict[str, Dict[str, object]],
    heat_lookup: Dict[str, Dict[str, object]],
    air_state_lookup: Dict[str, Dict[str, object]],
) -> Dict[str, int]:
    match_counts = {
        "final_rows": 0,
        "county_health_matches": 0,
        "state_heat_matches": 0,
        "state_air_toxics_matches": 0,
    }

    with existing_final_path.open("r", encoding="utf-8", errors="replace", newline="") as in_handle:
        reader = csv.DictReader(in_handle)
        fieldnames = list(reader.fieldnames or [])
        extra_fields = [
            "health_heat_deaths_year",
            "health_heat_related_deaths",
            "health_heat_related_deaths_status",
            "health_air_toxics_year",
            "health_county_total_cancer_risk_per_million",
            "health_county_pollutant_count",
            "health_county_top_pollutant",
            "health_county_top_pollutant_risk_per_million",
            "health_state_mean_county_total_cancer_risk_per_million",
            "health_state_max_county_total_cancer_risk_per_million",
            "health_state_top_county_by_cancer_risk",
            "health_state_top_county_cancer_risk_per_million",
            "health_state_top_pollutant_statewide",
        ]

        with out_path.open("w", encoding="utf-8", newline="") as out_handle:
            writer = csv.DictWriter(out_handle, fieldnames=fieldnames + extra_fields)
            writer.writeheader()

            for row in reader:
                match_counts["final_rows"] += 1
                county_fips = clean_text(row.get("em_FIPS", "")).zfill(5) if clean_text(row.get("em_FIPS", "")).isdigit() else ""
                state_key = normalize_name(row.get("State", ""))

                county_health = county_lookup.get(county_fips, {})
                heat = heat_lookup.get(state_key, {})
                air_state = air_state_lookup.get(state_key, {})

                if county_health:
                    match_counts["county_health_matches"] += 1
                if heat:
                    match_counts["state_heat_matches"] += 1
                if air_state:
                    match_counts["state_air_toxics_matches"] += 1

                row.update(
                    {
                        "health_heat_deaths_year": heat.get("year"),
                        "health_heat_related_deaths": heat.get("heat_related_deaths"),
                        "health_heat_related_deaths_status": heat.get("heat_related_deaths_status"),
                        "health_air_toxics_year": county_health.get("year") or air_state.get("air_toxics_year"),
                        "health_county_total_cancer_risk_per_million": county_health.get(
                            "county_total_cancer_risk_per_million"
                        ),
                        "health_county_pollutant_count": county_health.get("pollutant_count"),
                        "health_county_top_pollutant": county_health.get("top_pollutant"),
                        "health_county_top_pollutant_risk_per_million": county_health.get(
                            "top_pollutant_risk_per_million"
                        ),
                        "health_state_mean_county_total_cancer_risk_per_million": air_state.get(
                            "mean_county_total_cancer_risk_per_million"
                        ),
                        "health_state_max_county_total_cancer_risk_per_million": air_state.get(
                            "max_county_total_cancer_risk_per_million"
                        ),
                        "health_state_top_county_by_cancer_risk": air_state.get("top_county_by_cancer_risk"),
                        "health_state_top_county_cancer_risk_per_million": air_state.get(
                            "top_county_cancer_risk_per_million"
                        ),
                        "health_state_top_pollutant_statewide": air_state.get("top_pollutant_statewide"),
                    }
                )
                writer.writerow(row)

    return match_counts


def write_brainstorming_notes(
    path: Path,
    merge_counts: Dict[str, int],
    heat_rows: List[Dict[str, object]],
    joined_state_rows: List[Dict[str, object]],
) -> None:
    reported_heat = [row for row in heat_rows if row.get("heat_related_deaths") is not None]
    top_heat_row = max(reported_heat, key=lambda row: int(row["heat_related_deaths"])) if reported_heat else None
    top_risk_row = max(
        [row for row in joined_state_rows if row.get("max_county_total_cancer_risk_per_million") is not None],
        key=lambda row: float(row["max_county_total_cancer_risk_per_million"]),
    )

    text = "\n".join(
        [
            "# Health data brainstorming",
            "",
            "These health files do not line up perfectly in time or geography, so the cleanest story is:",
            "- Heat-related deaths are a state-level 2020 outcome measure.",
            "- Air toxics cancer risk is a county-level 2019 modeled exposure/risk measure.",
            "- The joined health summary brings them together at the state level, while the package-wide final file keeps county risk where possible and adds state heat context.",
            "",
            "Potential analysis ideas for your checkpoint:",
            "- Compare counties with higher modeled air-toxics cancer risk against 2020 air-quality burden indicators like `Max AQI`, `Days PM2.5`, or county emissions totals.",
            "- Look for states with both high summer heat deaths and high mean county cancer-risk burden to frame a cumulative environmental health vulnerability story.",
            "- Map the top pollutant driving cancer risk in each state and compare that to dominant point-source pollutants from the emissions file.",
            "- Test whether counties with higher emissions totals also have higher modeled county cancer risk, then discuss where the relationship is weak and why modeled risk is not the same as direct emissions volume.",
            "- Build a small set of case-study states: one with high heat mortality, one with high cancer-risk burden, and one high on both.",
            "- Use the year mismatch as a methodological note: treat this as exploratory triangulation, not a causal same-year estimate.",
            "",
            "Useful talking points:",
            f"- Highest reported state heat deaths in this file: {top_heat_row['state_name']} ({top_heat_row['heat_related_deaths']} deaths in {top_heat_row['year']})." if top_heat_row else "- Heat deaths are heavily suppressed for low-count states, so distributional summaries need caution.",
            f"- Highest state maximum county cancer risk in the joined state file: {top_risk_row['state_name']} ({top_risk_row['max_county_total_cancer_risk_per_million']} per million)." if top_risk_row else "- Air-toxics risk varies across counties inside a state, so state averages can hide hotspots.",
            f"- Coverage in the package-wide final merge: {merge_counts['county_health_matches']} of {merge_counts['final_rows']} county rows received county-level health risk, and {merge_counts['state_heat_matches']} of {merge_counts['final_rows']} rows received state heat context.",
        ]
    )
    path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and join health datasets for the air quality package")
    parser.add_argument(
        "--heat-zip",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/download (1).zip"),
        help="Zip containing state heat-related deaths data",
    )
    parser.add_argument(
        "--air-toxics-zip",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/download (3).zip"),
        help="Zip containing county air toxics cancer risk data",
    )
    parser.add_argument(
        "--existing-final",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/air_quality_package/final/final_combined_emissions_aqi_climate_2020.csv"),
        help="Existing final package file to extend with health fields",
    )
    parser.add_argument(
        "--health-out-dir",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/air_quality_package/cleaned health data"),
        help="Directory for cleaned health outputs",
    )
    parser.add_argument(
        "--final-out",
        type=Path,
        default=Path("/Users/saichimbili/Downloads/air_quality_package/final/final_combined_emissions_aqi_climate_health.csv"),
        help="Output path for package-wide final file with health context",
    )
    args = parser.parse_args()

    args.health_out_dir.mkdir(parents=True, exist_ok=True)
    args.final_out.parent.mkdir(parents=True, exist_ok=True)

    heat_rows, heat_lookup = build_heat_rows(args.heat_zip)
    air_clean_rows, air_county_rows, air_state_rows, county_lookup = build_air_toxics_rows(args.air_toxics_zip)
    joined_state_rows = join_health_state(heat_rows, air_state_rows)
    air_state_lookup = {normalize_name(str(row["state_name"])): row for row in air_state_rows}

    write_csv(args.health_out_dir / "cleaned_heat_related_deaths_state_2020.csv", heat_rows)
    write_csv(args.health_out_dir / "cleaned_air_toxics_cancer_risk_county_2019.csv", air_clean_rows)
    write_csv(args.health_out_dir / "air_toxics_cancer_risk_county_summary_2019.csv", air_county_rows)
    write_csv(args.health_out_dir / "air_toxics_cancer_risk_state_summary_2019.csv", air_state_rows)
    write_csv(args.health_out_dir / "joined_health_state_final.csv", joined_state_rows)

    merge_counts = merge_with_existing_final(
        args.existing_final,
        args.final_out,
        county_lookup,
        heat_lookup,
        air_state_lookup,
    )

    write_brainstorming_notes(
        args.health_out_dir / "health_analysis_brainstorm.md",
        merge_counts,
        heat_rows,
        joined_state_rows,
    )

    report = {
        "heat_rows": len(heat_rows),
        "air_toxics_county_pollutant_rows": len(air_clean_rows),
        "air_toxics_county_summary_rows": len(air_county_rows),
        "air_toxics_state_summary_rows": len(air_state_rows),
        "joined_health_state_rows": len(joined_state_rows),
        "merge_counts": merge_counts,
        "outputs": {
            "health_out_dir": str(args.health_out_dir),
            "extended_final": str(args.final_out),
        },
    }
    (args.health_out_dir / "health_join_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
