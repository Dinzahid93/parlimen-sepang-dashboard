# P.113 Sepang Road Authority Layer — Sources and Limitations

Generated: 3 August 2026

## What is included

`roads_authority_sepang.geojson` contains major drivable road segments from
OpenStreetMap that spatially fall inside the supplied P.113 Sepang boundary.
Each feature has `dun` and `pdm` attributes assigned from the supplied electoral
boundary files.

## Sources

- Road geometry, names, route references and OSM highway classes: OpenStreetMap
  contributors, https://www.openstreetmap.org/copyright (ODbL).
- Federal-road authority reference: Jabatan Kerja Raya Malaysia,
  https://www.jkr.gov.my/.
- State/local-road verification reference: Malaysia Road Records Information
  System (MARRIS), https://www.malaysia.gov.my/en/my-initiative/cyber-security-and-disaster-response-and-recovery/kesejahteraan-rakyat/sistem-maklumat-rekod-rekod-jalan-raya-malaysia-marris.
- Expressway oversight/concession reference: Lembaga Lebuhraya Malaysia,
  https://www.llm.gov.my/.
- Electoral clipping and assignment: the supplied `parliamentsepang.geojson`,
  `dun.geojson`, and `pdm.geojson` files.

## How to read verification status

- `Probable`: the authority category was inferred from a recognizable route
  reference (for example `E`, `B`, or a numeric route code), but was not verified
  road-by-road against a current official asset register.
- `Unverified`: OpenStreetMap identifies the road class, but does not establish
  the responsible owner or maintenance agency.

This is a useful first-pass dashboard layer, not a legal road-ownership register.
Confirm decisions about maintenance complaints or agency responsibility with
JKR, MARRIS, MPSepang, LLM, or the relevant concessionaire.
