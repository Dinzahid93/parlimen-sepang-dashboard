from pathlib import Path
import json
import re

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium


st.set_page_config(page_title="Parlimen Sepang (P.113) Dashboard", page_icon="🗺️", layout="wide")
password = st.text_input("Enter password", type="password")

if password != "0987":
    if password:
        st.error("Incorrect password.")
    st.stop()
ROOT = Path(__file__).parent
DATA = ROOT / "data"

FILES = {
    "parliament": DATA / "parliament.geojson",
    "dun": DATA / "dun.geojson",
    "pdm": DATA / "pdm.geojson",
    "polling": DATA / "polling_centres.geojson",
    "masjid": DATA / "masjid.geojson",
    "schools": DATA / "schools.geojson",
    "healthcare": DATA / "healthcare.geojson",
    "kampung": DATA / "kampung.geojson",
    "worship": DATA / "places_of_worship.geojson",
    "retail": DATA / "retail_markets.geojson",
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
healthcare = datasets["healthcare"]["features"]
kampungs = datasets["kampung"]["features"]
worship = datasets["worship"]["features"]
retail = datasets["retail"]["features"]

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
    c1, c2, c3 = st.columns(3)
    c1.metric("Parliament", "P.113 Sepang")
    c2.metric("Eligible voters", "168,039")
    c3.metric("PDM", len(pdms))
    c4, c5, c6 = st.columns(3)
    c4.metric("DUN", len(duns))
    c5.metric("Masjid", len(masjids))
    c6.metric("Schools", len(schools))
    c7, c8, c9 = st.columns(3)
    c7.metric("Healthcare facilities", len(healthcare))
    c8.metric("Kampung", len(kampungs))
    c9.metric("Other houses of worship", len(worship))
    c10, _, _ = st.columns(3)
    c10.metric("Retail & markets", len(retail))
    st.caption(
        "Data presented in this dashboard is compiled from open-source and publicly available datasets. "
        "Figures may differ slightly from official records due to incomplete coverage, source updates or data availability."
    )
    st.info("Additional cards and charts will appear here as community facility and issue datasets are added.")

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

    visible_healthcare = []
    for feature in healthcare:
        props = feature["properties"]
        if selected_dun and dun_code_from_name(props.get("dun")) != selected_dun:
            continue
        if selected_pdm_name != "All PDM" and props.get("pdm") != selected_pdm_name:
            continue
        visible_healthcare.append(feature)

    visible_kampungs = []
    for feature in kampungs:
        props = feature["properties"]
        if selected_dun and dun_code_from_name(props.get("dun")) != selected_dun:
            continue
        if selected_pdm_name != "All PDM" and props.get("pdm") != selected_pdm_name:
            continue
        visible_kampungs.append(feature)

    def filtered_points(features):
        result = []
        for feature in features:
            props = feature["properties"]
            if selected_dun and dun_code_from_name(props.get("dun")) != selected_dun:
                continue
            if selected_pdm_name != "All PDM" and props.get("pdm") != selected_pdm_name:
                continue
            result.append(feature)
        return result

    visible_worship = filtered_points(worship)
    visible_retail = filtered_points(retail)

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

    healthcare_group = folium.FeatureGroup(name="Healthcare (preliminary OSM)", show=True)
    for feature in visible_healthcare:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        popup = (
            f"<b>{props.get('name', 'Healthcare facility')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Phone:</b> {props.get('phone', '')}<br>"
            f"<b>Opening hours:</b> {props.get('opening_hours', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}"
        )
        marker_color = "#dc2626" if props.get("category") == "Hospital" else "#0891b2"
        marker_icon = "🏥" if props.get("category") == "Hospital" else "✚"
        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34), icon_anchor=(17, 17),
                html=f"<div style='width:34px;height:34px;border-radius:50%;background:{marker_color};color:white;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:bold'>{marker_icon}</div>",
            ),
            tooltip=props.get("name", "Healthcare facility"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(healthcare_group)
    healthcare_group.add_to(m)

    kampung_group = folium.FeatureGroup(name="Kampung", show=True)
    for feature in visible_kampungs:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        area = props.get("area_ha", "")
        popup = (
            f"<b>{props.get('name', 'Kampung')}</b><br><br>"
            f"<b>Type:</b> {props.get('kampung_type', '')}<br>"
            f"<b>District:</b> {props.get('district', '')}<br>"
            f"<b>Mukim:</b> {props.get('mukim', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Area:</b> {area} ha<br>"
            f"<b>Coordinate match:</b> {props.get('match_confidence', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}"
        )
        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34), icon_anchor=(17, 17),
                html="<div style='width:34px;height:34px;border-radius:50%;background:#7c3aed;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:19px'>🏘️</div>",
            ),
            tooltip=props.get("name", "Kampung"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(kampung_group)
    kampung_group.add_to(m)

    worship_group = folium.FeatureGroup(name="Other houses of worship", show=False)
    worship_icons = {"Surau / Musolla": "☪", "Church": "✝", "Hindu Temple": "🛕", "Buddhist Temple": "☸", "Chinese / Taoist Temple": "🏮", "Gurdwara": "☬"}
    for feature in visible_worship:
        props = feature["properties"]; lon, lat = feature["geometry"]["coordinates"][:2]
        popup = (f"<b>{props.get('name','')}</b><br><br><b>Category:</b> {props.get('category','')}<br>"
                 f"<b>Religion:</b> {props.get('religion','')}<br><b>DUN:</b> {props.get('dun','')}<br>"
                 f"<b>PDM:</b> {props.get('pdm','')}<br><b>Address:</b> {props.get('address','')}<br>"
                 f"<b>Status:</b> {props.get('verification_status','')}<br><b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}")
        icon = worship_icons.get(props.get("category"), "◆")
        folium.Marker([lat,lon], icon=folium.DivIcon(icon_size=(32,32),icon_anchor=(16,16),
            html=f"<div style='width:32px;height:32px;border-radius:50%;background:#a16207;color:white;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:18px'>{icon}</div>"),
            tooltip=props.get("name","House of worship"),popup=folium.Popup(popup,max_width=440)).add_to(worship_group)
    worship_group.add_to(m)

    retail_group = folium.FeatureGroup(name="Retail & markets", show=False)
    for feature in visible_retail:
        props = feature["properties"]; lon, lat = feature["geometry"]["coordinates"][:2]
        popup = (f"<b>{props.get('name','')}</b><br><br><b>Category:</b> {props.get('category','')}<br>"
                 f"<b>DUN:</b> {props.get('dun','')}<br><b>PDM:</b> {props.get('pdm','')}<br>"
                 f"<b>Address:</b> {props.get('address','')}<br><b>Opening hours:</b> {props.get('opening_hours','')}<br>"
                 f"<b>Premises:</b> {props.get('premises_type','')}<br><b>Status:</b> {props.get('verification_status','')}<br>"
                 f"<b>Latitude:</b> {lat}<br><b>Longitude:</b> {lon}")
        icon = "🧺" if props.get("group")=="Market" else "🛒"
        folium.Marker([lat,lon], icon=folium.DivIcon(icon_size=(32,32),icon_anchor=(16,16),
            html=f"<div style='width:32px;height:32px;border-radius:50%;background:#be123c;border:2px solid white;box-shadow:0 1px 5px #333;display:flex;align-items:center;justify-content:center;font-size:17px'>{icon}</div>"),
            tooltip=props.get("name","Retail / market"),popup=folium.Popup(popup,max_width=440)).add_to(retail_group)
    retail_group.add_to(m)

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
    healthcare_rows = []
    for feature in healthcare:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        healthcare_rows.append({
            "Facility": props.get("name", ""), "Category": props.get("category", ""),
            "DUN": props.get("dun", ""), "PDM": props.get("pdm", ""),
            "Address": props.get("address", ""), "Phone": props.get("phone", ""),
            "Opening hours": props.get("opening_hours", ""),
            "Verification": props.get("verification_status", ""),
            "Latitude": lat, "Longitude": lon,
        })
    healthcare_df = pd.DataFrame(healthcare_rows)
    kampung_rows = []
    for feature in kampungs:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        kampung_rows.append({
            "Kampung": props.get("name", ""), "Type": props.get("kampung_type", ""),
            "District": props.get("district", ""), "Mukim": props.get("mukim", ""),
            "DUN": props.get("dun", ""), "PDM": props.get("pdm", ""),
            "Area (ha)": props.get("area_ha", ""),
            "Match confidence": props.get("match_confidence", ""),
            "Verification": props.get("verification_status", ""),
            "Latitude": lat, "Longitude": lon,
        })
    kampung_df = pd.DataFrame(kampung_rows)
    worship_df = pd.DataFrame([{
        "Name": f["properties"].get("name",""), "Category": f["properties"].get("category",""),
        "Religion": f["properties"].get("religion",""), "DUN": f["properties"].get("dun",""),
        "PDM": f["properties"].get("pdm",""), "Address": f["properties"].get("address",""),
        "Verification": f["properties"].get("verification_status",""),
        "Latitude": f["geometry"]["coordinates"][1], "Longitude": f["geometry"]["coordinates"][0]
    } for f in worship])
    retail_df = pd.DataFrame([{
        "Name": f["properties"].get("name",""), "Group": f["properties"].get("group",""),
        "Category": f["properties"].get("category",""), "DUN": f["properties"].get("dun",""),
        "PDM": f["properties"].get("pdm",""), "Address": f["properties"].get("address",""),
        "Opening hours": f["properties"].get("opening_hours",""), "Premises": f["properties"].get("premises_type",""),
        "Verification": f["properties"].get("verification_status",""),
        "Latitude": f["geometry"]["coordinates"][1], "Longitude": f["geometry"]["coordinates"][0]
    } for f in retail])
    facility_type = st.selectbox(
        "Facility category", ["Select a category", "Masjid", "Other houses of worship", "Schools", "Healthcare", "Kampung", "Retail & Markets"]
    )
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
    elif facility_type == "Healthcare":
        shown_healthcare = healthcare_df
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            selected_healthcare_dun = st.selectbox(
                "Filter by DUN", ["All DUN"] + sorted(healthcare_df["DUN"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="healthcare_dun",
            )
        if selected_healthcare_dun != "All DUN":
            shown_healthcare = shown_healthcare[shown_healthcare["DUN"] == selected_healthcare_dun]
        with filter_col2:
            selected_healthcare_pdm = st.selectbox(
                "Filter by PDM", ["All PDM"] + sorted(shown_healthcare["PDM"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="healthcare_pdm",
            )
        if selected_healthcare_pdm != "All PDM":
            shown_healthcare = shown_healthcare[shown_healthcare["PDM"] == selected_healthcare_pdm]
        with filter_col3:
            selected_healthcare_type = st.selectbox(
                "Healthcare category", ["All categories"] + sorted(shown_healthcare["Category"].dropna().unique().tolist()),
                key="healthcare_category",
            )
        if selected_healthcare_type != "All categories":
            shown_healthcare = shown_healthcare[shown_healthcare["Category"] == selected_healthcare_type]
        healthcare_query = st.text_input("Search by facility name, category, address, DUN or PDM")
        if healthcare_query:
            shown_healthcare = shown_healthcare[
                shown_healthcare.astype(str).apply(lambda row: row.str.contains(healthcare_query, case=False, na=False).any(), axis=1)
            ]
        st.metric("Healthcare facilities shown", f"{len(shown_healthcare)} of {len(healthcare)}")
        st.dataframe(shown_healthcare, use_container_width=True, hide_index=True, height=520)
        st.caption("Preliminary OpenStreetMap dataset: 56 clinics and 5 hospitals. Verify against current MOH/JKN and local records before treating this as an official total.")
    elif facility_type == "Kampung":
        shown_kampungs = kampung_df
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            selected_kampung_dun = st.selectbox(
                "Filter by DUN", ["All DUN"] + sorted(kampung_df["DUN"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="kampung_dun",
            )
        if selected_kampung_dun != "All DUN":
            shown_kampungs = shown_kampungs[shown_kampungs["DUN"] == selected_kampung_dun]
        with filter_col2:
            selected_kampung_pdm = st.selectbox(
                "Filter by PDM", ["All PDM"] + sorted(shown_kampungs["PDM"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="kampung_pdm",
            )
        if selected_kampung_pdm != "All PDM":
            shown_kampungs = shown_kampungs[shown_kampungs["PDM"] == selected_kampung_pdm]
        with filter_col3:
            selected_kampung_mukim = st.selectbox(
                "Filter by Mukim", ["All Mukim"] + sorted(shown_kampungs["Mukim"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="kampung_mukim",
            )
        if selected_kampung_mukim != "All Mukim":
            shown_kampungs = shown_kampungs[shown_kampungs["Mukim"] == selected_kampung_mukim]
        with filter_col4:
            selected_kampung_type = st.selectbox(
                "Kampung type", ["All types"] + sorted(shown_kampungs["Type"].dropna().loc[lambda s: s != ""].unique().tolist()),
                key="kampung_type",
            )
        if selected_kampung_type != "All types":
            shown_kampungs = shown_kampungs[shown_kampungs["Type"] == selected_kampung_type]
        kampung_query = st.text_input("Search by kampung name, district, mukim, type, DUN or PDM")
        if kampung_query:
            shown_kampungs = shown_kampungs[
                shown_kampungs.astype(str).apply(lambda row: row.str.contains(kampung_query, case=False, na=False).any(), axis=1)
            ]
        st.metric("Kampung shown", f"{len(shown_kampungs)} of {len(kampungs)}")
        st.dataframe(shown_kampungs, use_container_width=True, hide_index=True, height=520)
        st.caption("Mapped village points matched from the supplied Selangor village list and spatially filtered to the P.113 boundary.")
    elif facility_type in ("Other houses of worship", "Retail & Markets"):
        source_df = worship_df if facility_type == "Other houses of worship" else retail_df
        shown = source_df
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            selected_dun2 = st.selectbox("Filter by DUN", ["All DUN"] + sorted(source_df["DUN"].dropna().loc[lambda s:s!=""].unique().tolist()), key=f"{facility_type}_dun")
        if selected_dun2 != "All DUN": shown = shown[shown["DUN"] == selected_dun2]
        with filter_col2:
            selected_pdm2 = st.selectbox("Filter by PDM", ["All PDM"] + sorted(shown["PDM"].dropna().loc[lambda s:s!=""].unique().tolist()), key=f"{facility_type}_pdm")
        if selected_pdm2 != "All PDM": shown = shown[shown["PDM"] == selected_pdm2]
        with filter_col3:
            selected_category2 = st.selectbox("Category", ["All categories"] + sorted(shown["Category"].dropna().unique().tolist()), key=f"{facility_type}_category")
        if selected_category2 != "All categories": shown = shown[shown["Category"] == selected_category2]
        search2 = st.text_input("Search by name, category, address, DUN or PDM", key=f"{facility_type}_search")
        if search2:
            shown = shown[shown.astype(str).apply(lambda row: row.str.contains(search2, case=False, na=False).any(), axis=1)]
        st.metric(f"{facility_type} shown", f"{len(shown)} of {len(source_df)}")
        st.dataframe(shown, use_container_width=True, hide_index=True, height=520)
        st.caption("OpenStreetMap starting dataset spatially filtered to P.113. Verify unmapped, unnamed and temporary entities with local records.")
    else:
        st.info("Choose a facility category to display its records.")
    st.caption("Future categories can be added using the same DUN/PDM structure.")

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
    selected_dataset = st.selectbox("Dataset", ["Polling centres", "Masjid", "Other houses of worship", "Schools", "Healthcare", "Kampung", "Retail & Markets"])
    if selected_dataset == "Polling centres":
        st.caption("These 51 records provide the polling-centre markers shown on the interactive map.")
        st.dataframe(polling_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Masjid":
        st.caption("These 43 records provide the masjid markers shown on the interactive map.")
        st.dataframe(facility_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Other houses of worship":
        st.caption(f"These {len(worship_df)} open-source records include surau/musolla, churches and temples within P.113.")
        st.dataframe(worship_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Schools":
        st.caption("These 84 preliminary OSM records provide the school markers shown on the interactive map.")
        st.dataframe(school_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Healthcare":
        st.caption("These 61 preliminary OSM records provide the clinic and hospital markers shown on the interactive map.")
        st.dataframe(healthcare_df, use_container_width=True, hide_index=True)
    elif selected_dataset == "Kampung":
        st.caption("These 32 mapped kampung records are spatially located inside the P.113 boundary.")
        st.dataframe(kampung_df, use_container_width=True, hide_index=True)
    else:
        st.caption(f"These {len(retail_df)} priority retail and market records are grouped by DUN and PDM.")
        st.dataframe(retail_df, use_container_width=True, hide_index=True)
