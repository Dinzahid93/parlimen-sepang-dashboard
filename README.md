# Parlimen Sepang (P.113) Dashboard

Interactive Streamlit dashboard built from four QGIS-exported GeoJSON layers. It preserves the original names and descriptions while displaying structured pop-ups at runtime without modifying the source files.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Update the website data

1. Finish and save edits to the source layer in QGIS.
2. Save edits to the four working GeoJSON layers.
3. Ensure the updated files remain in the `data` folder.
4. Commit and push the changed GeoJSON files to the repository used by Streamlit Community Cloud.

Saving the `.qgz` QGIS project alone does not update a deployed website. The deployed app changes only after its data file or application code is updated and redeployed.

## Required data files

- `data/parliament.geojson`
- `data/dun.geojson`
- `data/pdm.geojson`
- `data/polling_centres.geojson`
- `data/masjid.geojson`
- `data/schools.geojson`

The app continues to work with the current combined `description` fields. New structured layers such as schools, mosques and clinics can be added later.
