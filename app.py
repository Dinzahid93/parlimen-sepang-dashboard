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


def prepared_feature(feature):
    item = json.loads(json.dumps(feature))
    props = item.setdefault("properties", {})
    extracted = fields_from_description(props.get("description", ""))
    props.update({f"info_{k}": v for k, v in extracted.items()})
    return item, extracted


def add_geojson_feature(group, feature, color, weight=2, fill_opacity=0.1, label="Feature"):
    item, extracted = prepared_feature(feature)
    props = item["properties"]
    popup_fields = ["Name"]
    popup_aliases = [f"{label}:"]
    preferred = [
        ("info_KODDMA", "PDM code:"), ("info_NAMADMA", "PDM name:"),
        ("info_KODDUNA", "DUN code:"), ("info_NAMADUNA", "DUN name:"),
        ("info_JUMLAH_PEM", "Registered voters:"), ("info_LUAS", "Area:"),
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

st.title("Parlimen Sepang (P.113) Dashboard")
st.caption("Local information, facilities and issue-monitoring dashboard")

overview_tab, map_tab, facilities_tab, issues_tab, data_tab = st.tabs(
    ["Overview", "Interactive Map", "Facilities", "Issues Reported", "Data Table"]
)

with overview_tab:
    voter_total = 0
    for feature in pdms:
        values = fields_from_description(feature["properties"].get("description", ""))
        try:
            voter_total += int(float(values.get("JUMLAH_PEM", 0)))
        except ValueError:
            pass
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Parliament", "P.113 Sepang")
    c2.metric("DUN", len(duns))
    c3.metric("PDM", len(pdms))
    c4.metric("Registered voters", f"{voter_total:,}")
    st.info("Additional cards and charts will appear here when school, mosque, clinic and issue datasets are added.")

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

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=680, returned_objects=[])

with facilities_tab:
    st.subheader("Facilities")
    st.info("Reserved for schools, mosques, surau, clinics, community halls and other facilities.")

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
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

