from pathlib import Path
import json
import re

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium


st.set_page_config(page_title="Parlimen Sepang (P.113) Dashboard", page_icon="🗺️", layout="wide")
ROOT = Path(__file__).parent
DATA = ROOT / "data"

FILES = {
    "parliament": DATA / "parliament.geojson",
    "dun": DATA / "dun.geojson",
    "pdm": DATA / "pdm.geojson",
    "polling": DATA / "polling_centres.geojson",
    "masjid": DATA / "masjid.geojson",
    "schools": DATA / "schools.geojson",
}

DUN_COLORS = {"54": "#84b83f", "55": "#2474b5", "56": "#b12a90"}
DUN_LABELS = {"54": "N.54 Tanjong Sepat", "55": "N.55 Dengkil", "56": "N.56 Sungai Pelek"}


@st.cache_data(show_spinner=False)
def read_geojson(path, modified):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def fields_from_description(description):
    text = re.sub(r"<br\s*/?>", "\n", description or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    result = {}
    colon_labels = {"No.", "Kod Pusat Mengundi", "Nama DUN", "Pusat Mengundi", "Latitude", "Longitude"}
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() in colon_labels:
                result[key.strip()] = value.strip()
                continue
        match = re.match(r"^(KODDUNA|NAMADUNA|KODDMA|NAMADMA|LUAS|Status|JUMLAH_PEM|SHAPE_Leng)\s+(.*)$", line, re.I)
        if match:
            result[match.group(1).upper()] = match.group(2).strip()
    return result


def dun_code_from_name(name):
    match = re.search(r"(?:N\.|113/)(54|55|56)", name or "", flags=re.I)
    return match.group(1) if match else None


def point_in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        if ((yi > lat) != (yj > lat)) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lon, lat, geometry):
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for polygon in polygons:
        if point_in_ring(lon, lat, polygon[0]) and not any(point_in_ring(lon, lat, hole) for hole in polygon[1:]):
            return True
    return False


def prepared_feature(feature):
    item = json.loads(json.dumps(feature))
    props = item.setdefault("properties", {})
    extracted = fields_from_description(props.get("description", ""))
    props.update({f"info_{k}": v for k, v in extracted.items()})
    if extracted.get("LUAS"):
        try:
            props["info_AREA_KM2"] = f"{float(extracted['LUAS'].replace(',', '')) / 1_000_000:,.2f} km²"
        except ValueError:
            pass
    return item, extracted


def add_geojson_feature(group, feature, color, weight=2, fill_opacity=0.1, label="Feature"):
    item, extracted = prepared_feature(feature)
    props = item["properties"]
    popup_fields = ["Name"]
    popup_aliases = [f"{label}:"]
    preferred = [
        ("info_KODDMA", "PDM code:"), ("info_NAMADMA", "PDM name:"),
        ("info_KODDUNA", "DUN code:"), ("info_NAMADUNA", "DUN name:"),
        ("info_JUMLAH_PEM", "Legacy voter count:"), ("info_AREA_KM2", "Area:"),
    ]
    for field, alias in preferred:
        if field in props:
            popup_fields.append(field)
            popup_aliases.append(alias)
    folium.GeoJson(
        item,
        style_function=lambda _, c=color, w=weight, o=fill_opacity: {
            "color": c, "weight": w, "fillColor": c, "fillOpacity": o
        },
        highlight_function=lambda _: {"weight": 5, "fillOpacity": 0.25},
        tooltip=folium.GeoJsonTooltip(fields=["Name"], aliases=[f"{label}:"]),
        popup=folium.GeoJsonPopup(fields=popup_fields, aliases=popup_aliases, localize=True),
    ).add_to(group)


missing = [str(path) for path in FILES.values() if not path.exists()]
if missing:
    st.error("Missing dashboard data file(s): " + ", ".join(missing))
    st.stop()

datasets = {key: read_geojson(str(path), path.stat().st_mtime) for key, path in FILES.items()}
parliament = datasets["parliament"]["features"]
duns = datasets["dun"]["features"]
pdms = datasets["pdm"]["features"]
polling = datasets["polling"]["features"]
masjids = datasets["masjid"]["features"]
schools = datasets["schools"]["features"]

for masjid in masjids:
    lon, lat = masjid["geometry"]["coordinates"][:2]
    props = masjid.setdefault("properties", {})
    props["_dun_code"] = next(
        (dun_code_from_name(f["properties"].get("Name")) for f in duns if point_in_geometry(lon, lat, f["geometry"])), None
    )
    props["_pdm_name"] = next(
        (f["properties"].get("Name", "") for f in pdms if point_in_geometry(lon, lat, f["geometry"])), ""
    )

st.title("Parlimen Sepang (P.113) Dashboard")
st.caption("Local information, facilities and issue-monitoring dashboard")

overview_tab, map_tab, facilities_tab, issues_tab, data_tab = st.tabs(
    ["Overview", "Interactive Map", "Facilities", "Issues Reported", "Data Explorer"]
)

with overview_tab:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Parliament", "P.113 Sepang")
    c2.metric("DUN", len(duns))
    c3.metric("PDM", len(pdms))
    c4.metric("Masjid", len(masjids))
    c5.metric("Schools*", len(schools))
    c6.metric("Eligible voters", "168,039")
    st.caption("*Preliminary OpenStreetMap school count; verification against KPM/JPN records is pending.")
    st.caption("Eligible voters: official GE15 electoral roll (2022). Legacy PDM voter attributes are retained only in feature pop-ups.")
    st.info("Additional cards and charts will appear here when surau, clinic and issue datasets are added.")

with map_tab:
    with st.sidebar:
        st.header("Map controls")
        selected_dun_label = st.selectbox("Filter by DUN", ["All DUN"] + list(DUN_LABELS.values()))
        selected_dun = next((code for code, label in DUN_LABELS.items() if label == selected_dun_label), None)
        selected_pdm_name = st.selectbox(
            "Filter by PDM",
            ["All PDM"] + [f["properties"].get("Name", "") for f in pdms if not selected_dun or dun_code_from_name(f["properties"].get("Name")) == selected_dun],
        )
        st.caption("Use the layer button on the map to turn individual layers on or off.")

    visible_pdms = [f for f in pdms if (not selected_dun or dun_code_from_name(f["properties"].get("Name")) == selected_dun)]
    if selected_pdm_name != "All PDM":
        visible_pdms = [f for f in visible_pdms if f["properties"].get("Name") == selected_pdm_name]

    visible_polling = []
    for feature in polling:
        values = fields_from_description(feature["properties"].get("description", ""))
        code = values.get("Kod Pusat Mengundi", "")
        if selected_dun and f"/{selected_dun}/" not in code:
            continue
        if selected_pdm_name != "All PDM" and code not in selected_pdm_name:
            continue
        visible_polling.append(feature)

    visible_masjids = []
    for feature in masjids:
        props = feature["properties"]
        if selected_dun and props.get("_dun_code") != selected_dun:
            continue
        if selected_pdm_name != "All PDM" and props.get("_pdm_name") != selected_pdm_name:
            continue
        visible_masjids.append(feature)

    visible_schools = []
    for feature in schools:
        props = feature["properties"]
        if selected_dun and dun_code_from_name(props.get("dun")) != selected_dun:
            continue
        if selected_pdm_name != "All PDM" and props.get("pdm") != selected_pdm_name:
            continue
        visible_schools.append(feature)

    m = folium.Map(location=[2.80, 101.67], zoom_start=10, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=True).add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite", show=False,
    ).add_to(m)
    Fullscreen(position="topright").add_to(m)

    parliament_group = folium.FeatureGroup(name="Parliament boundary", show=True)
    for feature in parliament:
        add_geojson_feature(parliament_group, feature, "#e31a1c", 4, 0.0, "Parliament")
    parliament_group.add_to(m)

    dun_group = folium.FeatureGroup(name="DUN boundaries", show=True)
    for feature in duns:
        code = dun_code_from_name(feature["properties"].get("Name")) or "55"
        if not selected_dun or code == selected_dun:
            add_geojson_feature(dun_group, feature, DUN_COLORS[code], 4, 0.06, "DUN")
    dun_group.add_to(m)

    pdm_group = folium.FeatureGroup(name="PDM boundaries", show=True)
    for feature in visible_pdms:
        code = dun_code_from_name(feature["properties"].get("Name")) or "55"
        add_geojson_feature(pdm_group, feature, DUN_COLORS[code], 2, 0.12, "PDM")
    pdm_group.add_to(m)

    polling_group = folium.FeatureGroup(name="Polling centres", show=True)
    for feature in visible_polling:
        props = feature["properties"]
        values = fields_from_description(props.get("description", ""))
        lon, lat = feature["geometry"]["coordinates"][:2]
        details = "".join(
            f"<b>{label}:</b> {values.get(field, '')}<br>" for field, label in [
                ("Kod Pusat Mengundi", "Code"), ("Nama DUN", "DUN"),
                ("Pusat Mengundi", "Polling centre"), ("Latitude", "Latitude"), ("Longitude", "Longitude")
            ]
        )
        folium.CircleMarker(
            [lat, lon], radius=6, color="#9a3412", weight=2, fill=True,
            fill_color="#fb923c", fill_opacity=0.95,
            tooltip=props.get("Name", "Polling centre"),
            popup=folium.Popup(f"<b>{props.get('Name','')}</b><br><br>{details}", max_width=400),
        ).add_to(polling_group)
    polling_group.add_to(m)

    masjid_group = folium.FeatureGroup(name="Masjid", show=True)
    for feature in visible_masjids:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        popup = (
            f"<b>{props.get('Field3', 'Masjid')}</b><br><br>"
            f"<b>District:</b> {props.get('Field1', '')}<br>"
            f"<b>Mukim:</b> {props.get('Field2', '')}<br>"
            f"<b>Address:</b> {props.get('Field4', '')}<br>"
            f"<b>PDM:</b> {props.get('_pdm_name', '')}<br>"
            f"<b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}"
        )
        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34), icon_anchor=(17, 17),
                html="<div style='width:34px;height:34px;border-radius:50%;background:#15803d;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:20px'>🕌</div>",
            ),
            tooltip=props.get("Field3", "Masjid"),
            popup=folium.Popup(popup, max_width=430),
        ).add_to(masjid_group)
    masjid_group.add_to(m)

    school_group = folium.FeatureGroup(name="Schools (preliminary OSM)", show=True)
    for feature in visible_schools:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        popup = (
            f"<b>{props.get('name', 'School')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}"
        )
        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34), icon_anchor=(17, 17),
                html="<div style='width:34px;height:34px;border-radius:50%;background:#1d4ed8;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:20px'>🏫</div>",
            ),
            tooltip=props.get("name", "School"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(school_group)
    school_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=680, returned_objects=[])

with facilities_tab:
    st.subheader("Facilities")
    facility_rows = []
    for feature in masjids:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        facility_rows.append({
            "Masjid": props.get("Field3", ""), "District": props.get("Field1", ""),
            "Mukim": props.get("Field2", ""), "DUN": DUN_LABELS.get(props.get("_dun_code"), ""),
            "PDM": props.get("_pdm_name", ""), "Address": props.get("Field4", ""),
            "Latitude": lat, "Longitude": lon,
        })
    facility_df = pd.DataFrame(facility_rows)
    school_rows = []
    for feature in schools:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        school_rows.append({
            "School": props.get("name", ""), "Category": props.get("category", ""),
            "DUN": props.get("dun", ""), "PDM": props.get("pdm", ""),
            "Address": props.get("address", ""), "Verification": props.get("verification_status", ""),
            "Latitude": lat, "Longitude": lon,
        })
    school_df = pd.DataFrame(school_rows)
    facility_type = st.selectbox("Facility category", ["Select a category", "Masjid", "Schools"])
    if facility_type == "Masjid":
        shown_facilities = facility_df
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            selected_facility_dun = st.selectbox(
                "Filter by DUN",
                ["All DUN"] + sorted(facility_df["DUN"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="facility_dun",
            )
        if selected_facility_dun != "All DUN":
            shown_facilities = shown_facilities[shown_facilities["DUN"] == selected_facility_dun]
        with filter_col2:
            selected_facility_pdm = st.selectbox(
                "Filter by PDM",
                ["All PDM"] + sorted(shown_facilities["PDM"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="facility_pdm",
            )
        if selected_facility_pdm != "All PDM":
            shown_facilities = shown_facilities[shown_facilities["PDM"] == selected_facility_pdm]
        query = st.text_input("Search by masjid name, mukim, address, DUN or PDM")
        if query:
            shown_facilities = shown_facilities[
                shown_facilities.astype(str).apply(lambda row: row.str.contains(query, case=False, na=False).any(), axis=1)
            ]
        st.metric("Masjid shown", f"{len(shown_facilities)} of {len(masjids)}")
        st.dataframe(shown_facilities, use_container_width=True, hide_index=True, height=520)
    elif facility_type == "Schools":
        shown_schools = school_df
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            selected_school_dun = st.selectbox(
                "Filter by DUN", ["All DUN"] + sorted(school_df["DUN"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="school_dun",
            )
        if selected_school_dun != "All DUN":
            shown_schools = shown_schools[shown_schools["DUN"] == selected_school_dun]
        with filter_col2:
            selected_school_pdm = st.selectbox(
                "Filter by PDM", ["All PDM"] + sorted(shown_schools["PDM"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="school_pdm",
            )
        if selected_school_pdm != "All PDM":
            shown_schools = shown_schools[shown_schools["PDM"] == selected_school_pdm]
        with filter_col3:
            selected_school_type = st.selectbox(
                "School category", ["All categories"] + sorted(shown_schools["Category"].dropna().unique().tolist()),
                key="school_category",
            )
        if selected_school_type != "All categories":
            shown_schools = shown_schools[shown_schools["Category"] == selected_school_type]
        school_query = st.text_input("Search by school name, category, address, DUN or PDM")
        if school_query:
            shown_schools = shown_schools[
                shown_schools.astype(str).apply(lambda row: row.str.contains(school_query, case=False, na=False).any(), axis=1)
            ]
        st.metric("Schools shown", f"{len(shown_schools)} of {len(schools)}")
        st.dataframe(shown_schools, use_container_width=True, hide_index=True, height=520)
        st.caption("Preliminary OpenStreetMap dataset. Verify against current KPM/JPN records before treating this as an official total.")
    else:
        st.info("Choose a facility category to display its records.")
    st.caption("Future categories: surau, clinics, community halls and others.")

with issues_tab:
    st.subheader("Issues Reported")
    st.info("Reserved for issue location, category, description, status, responsible party and follow-up history.")

with data_tab:
    rows = []
    for feature in polling:
        values = fields_from_description(feature["properties"].get("description", ""))
        lon, lat = feature["geometry"]["coordinates"][:2]
        rows.append({
            "PDM": feature["properties"].get("Name", ""),
            "Code": values.get("Kod Pusat Mengundi", ""),
            "DUN": values.get("Nama DUN", ""),
            "Polling centre": values.get("Pusat Mengundi", ""),
            "Latitude": lat, "Longitude": lon,
        })
    polling_df = pd.DataFrame(rows)
    selected_dataset = st.selectbox("Dataset", ["Polling centres", "Masjid", "Schools"])
    if selected_dataset == "Polling centres":
        st.caption("These 51 records provide the polling-centre markers shown on the interactive map.")
        st.dataframe(polling_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Masjid":
        st.caption("These 43 records provide the masjid markers shown on the interactive map.")
        st.dataframe(facility_df, use_container_width=True, hide_index=True)
    else:
        st.caption("These 84 preliminary OSM records provide the school markers shown on the interactive map.")
        st.dataframe(school_df, use_container_width=True, hide_index=True)
