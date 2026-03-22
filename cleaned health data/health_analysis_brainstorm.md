# Health data brainstorming

These health files do not line up perfectly in time or geography, so the cleanest story is:
- Heat-related deaths are a state-level 2020 outcome measure.
- Air toxics cancer risk is a county-level 2019 modeled exposure/risk measure.
- The joined health summary brings them together at the state level, while the package-wide final file keeps county risk where possible and adds state heat context.

Potential analysis ideas for your checkpoint:
- Compare counties with higher modeled air-toxics cancer risk against 2020 air-quality burden indicators like `Max AQI`, `Days PM2.5`, or county emissions totals.
- Look for states with both high summer heat deaths and high mean county cancer-risk burden to frame a cumulative environmental health vulnerability story.
- Map the top pollutant driving cancer risk in each state and compare that to dominant point-source pollutants from the emissions file.
- Test whether counties with higher emissions totals also have higher modeled county cancer risk, then discuss where the relationship is weak and why modeled risk is not the same as direct emissions volume.
- Build a small set of case-study states: one with high heat mortality, one with high cancer-risk burden, and one high on both.
- Use the year mismatch as a methodological note: treat this as exploratory triangulation, not a causal same-year estimate.

Useful talking points:
- Highest reported state heat deaths in this file: Arizona (373 deaths in 2020).
- Highest state maximum county cancer risk in the joined state file: Georgia (85.1 per million).
- Coverage in the package-wide final merge: 979 of 1006 county rows received county-level health risk, and 990 of 1006 rows received state heat context.
