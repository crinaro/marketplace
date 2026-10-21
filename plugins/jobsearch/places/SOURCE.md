# us_places.csv.gz

One row per US place (`name,state,lat,lon`), used by the location screen to estimate how far a role is from a commute anchor (jobsearch 0.70.0, dev #729).

- **Source:** US Census Bureau, 2024 Gazetteer Files, national places file (`2024_Gaz_place_national.txt`). This is a US federal government work and in the public domain.
- **Coordinates:** the Census internal point of each place, rounded to 4 decimal places.
- **Built by:** the maintenance repository's place-table generator (maintainer tooling, not shipped). The table is regenerated, never hand-edited.

It holds public place names only. No profile data is read or written to build it.
