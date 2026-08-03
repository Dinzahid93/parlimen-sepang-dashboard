from pathlib import Path
import json
import math
import re

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen, MeasureControl
from streamlit_folium import st_folium


st.set_page_config(
    page_title="Parlimen Sepang (P.113) Dashboard",
    page_icon="🗺️",
    layout="wide",
)

password = st.text_input("Enter password", type="password")

if password != "4732":
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
    "speedmart": DATA / "speedmart.geojson",
    "kkmart": DATA / "kkmart.geojson",
    "seven_eleven": DATA / "7eleven.geojson",
    "pasar_tani": DATA / "pasar_tani.geojson",
    "pasar_pagi": DATA / "pasar_pagi.geojson",
    "roads": DATA / "roads_authority_sepang.geojson",
    "vulnerable": DATA / "vulnerable_facilities.geojson",
}

DUN_COLORS = {"54": "#84b83f", "55": "#2474b5", "56": "#b12a90"}
DUN_LABELS = {
    "54": "N.54 Tanjong Sepat",
    "55": "N.55 Dengkil",
    "56": "N.56 Sungai Pelek",
}

VULNERABLE_ICONS = {
    "Nursing Home": "🏠",
    "Elderly Care Home": "🏠",
    "Residential Care Facility": "🏠",
    "Orphanage": "👶",
    "Children's Home": "👶",
    "Disability Care Centre": "♿",
    "Autism Centre": "♿",
    "Rehabilitation Centre": "♿",
    "Dialysis Centre": "🏥",
    "Government Dialysis Centre": "🏥",
    "NGO Dialysis Centre": "🏥",
    "Private Dialysis Centre": "🏥",
}

VULNERABLE_COLORS = {
    "Nursing Home": "#7c2d12",
    "Elderly Care Home": "#7c2d12",
    "Residential Care Facility": "#9a3412",
    "Orphanage": "#0369a1",
    "Children's Home": "#0369a1",
    "Disability Care Centre": "#6d28d9",
    "Autism Centre": "#6d28d9",
    "Rehabilitation Centre": "#6d28d9",
    "Dialysis Centre": "#be123c",
    "Government Dialysis Centre": "#be123c",
    "NGO Dialysis Centre": "#be123c",
    "Private Dialysis Centre": "#be123c",
}


@st.cache_data(show_spinner=False)
def read_geojson(path: str, modified: float):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def fields_from_description(description):
    text = re.sub(r"<br\s*/?>", "\n", description or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    result = {}
    colon_labels = {
        "No.",
        "Kod Pusat Mengundi",
        "Nama DUN",
        "Pusat Mengundi",
        "Latitude",
        "Longitude",
    }
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() in colon_labels:
                result[key.strip()] = value.strip()
                continue
        match = re.match(
            r"^(KODDUNA|NAMADUNA|KODDMA|NAMADMA|LUAS|Status|JUMLAH_PEM|SHAPE_Leng)\s+(.*)$",
            line,
            re.I,
        )
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
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            x_intersection = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
            if lon < x_intersection:
                inside = not inside
        j = i
    return inside


def point_in_geometry(lon, lat, geometry):
    if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return False
    polygons = (
        geometry["coordinates"]
        if geometry["type"] == "MultiPolygon"
        else [geometry["coordinates"]]
    )
    for polygon in polygons:
        if not polygon:
            continue
        if point_in_ring(lon, lat, polygon[0]) and not any(
            point_in_ring(lon, lat, hole) for hole in polygon[1:]
        ):
            return True
    return False


def point_inside_parliament(lon, lat, parliament_features):
    return any(
        point_in_geometry(lon, lat, feature.get("geometry", {}))
        for feature in parliament_features
    )


def spatially_assign(feature, duns, pdms):
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") != "Point" or len(coordinates) < 2:
        return feature

    lon, lat = coordinates[:2]
    props = feature.setdefault("properties", {})

    matched_dun = next(
        (
            f
            for f in duns
            if point_in_geometry(lon, lat, f.get("geometry", {}))
        ),
        None,
    )
    matched_pdm = next(
        (
            f
            for f in pdms
            if point_in_geometry(lon, lat, f.get("geometry", {}))
        ),
        None,
    )

    if matched_dun:
        code = dun_code_from_name(matched_dun.get("properties", {}).get("Name", ""))
        props["dun"] = DUN_LABELS.get(
            code,
            matched_dun.get("properties", {}).get("Name", ""),
        )
    if matched_pdm:
        props["pdm"] = matched_pdm.get("properties", {}).get("Name", "")

    return feature


def normalized_place_name(value):
    """Normalize facility names so records from different files can be matched."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def polling_centre_is_school(name):
    """Return True when a polling-centre name clearly identifies a school."""
    text = re.sub(r"\s+", " ", (name or "").upper()).strip()
    school_patterns = [
        r"\bSEKOLAH\b",
        r"\bSK\b",
        r"\bSMK\b",
        r"\bSJK\s*\(?[CT]\)?\b",
        r"\bSJKT\b",
        r"\bSJ(K|KC|KT)\b",
        r"\bSRA\b",
        r"\bKAFA\b",
        r"\bMADRASAH\b",
        r"\bKOLEJ\b",
    ]
    return any(re.search(pattern, text, flags=re.I) for pattern in school_patterns)


def add_school_polling_centres(school_features, polling_features, duns, pdms):
    """Add school-based polling centres to the school dataset without duplicates."""
    combined = list(school_features)
    known_names = {
        normalized_place_name(f.get("properties", {}).get("name", ""))
        for f in combined
        if f.get("properties", {}).get("name")
    }
    known_coordinates = {
        tuple(round(float(value), 6) for value in f.get("geometry", {}).get("coordinates", [])[:2])
        for f in combined
        if f.get("geometry", {}).get("type") == "Point"
        and len(f.get("geometry", {}).get("coordinates", [])) >= 2
    }

    for feature in polling_features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        source_props = feature.get("properties", {})
        values = fields_from_description(source_props.get("description", ""))
        name = (
            values.get("Pusat Mengundi")
            or source_props.get("Name")
            or source_props.get("name")
            or ""
        ).strip()
        if not polling_centre_is_school(name):
            continue

        name_key = normalized_place_name(name)
        coordinate_key = tuple(round(float(value), 6) for value in coordinates[:2])
        if name_key in known_names or coordinate_key in known_coordinates:
            continue

        school_feature = {
            "type": "Feature",
            "geometry": json.loads(json.dumps(geometry)),
            "properties": {
                "name": name,
                "category": "School / Polling Centre",
                "address": source_props.get("address", ""),
                "verification_status": "From polling-centre dataset",
                "is_polling_centre": True,
                "polling_centre_code": values.get("Kod Pusat Mengundi", ""),
            },
        }
        combined.append(spatially_assign(school_feature, duns, pdms))
        known_names.add(name_key)
        known_coordinates.add(coordinate_key)

    return combined


def prepared_feature(feature):
    item = json.loads(json.dumps(feature))
    props = item.setdefault("properties", {})
    extracted = fields_from_description(props.get("description", ""))
    props.update({f"info_{key}": value for key, value in extracted.items()})

    if extracted.get("LUAS"):
        try:
            area_m2 = float(extracted["LUAS"].replace(",", ""))
            props["info_AREA_KM2"] = f"{area_m2 / 1_000_000:,.2f} km²"
        except ValueError:
            pass

    return item


def add_geojson_feature(
    group,
    feature,
    color,
    weight=2,
    fill_opacity=0.1,
    label="Feature",
):
    item = prepared_feature(feature)
    props = item["properties"]
    popup_fields = ["Name"]
    popup_aliases = [f"{label}:"]

    preferred = [
        ("info_KODDMA", "PDM code:"),
        ("info_NAMADMA", "PDM name:"),
        ("info_KODDUNA", "DUN code:"),
        ("info_NAMADUNA", "DUN name:"),
        ("info_JUMLAH_PEM", "Legacy voter count:"),
        ("info_AREA_KM2", "Area:"),
    ]

    for field, alias in preferred:
        if field in props:
            popup_fields.append(field)
            popup_aliases.append(alias)

    folium.GeoJson(
        item,
        style_function=lambda _, c=color, w=weight, o=fill_opacity: {
            "color": c,
            "weight": w,
            "fillColor": c,
            "fillOpacity": o,
        },
        highlight_function=lambda _: {"weight": 5, "fillOpacity": 0.25},
        tooltip=folium.GeoJsonTooltip(
            fields=["Name"],
            aliases=[f"{label}:"],
        ),
        popup=folium.GeoJsonPopup(
            fields=popup_fields,
            aliases=popup_aliases,
            localize=True,
        ),
    ).add_to(group)


def filter_points(features, selected_dun, selected_pdm_name):
    result = []
    for feature in features:
        props = feature.get("properties", {})
        if selected_dun and dun_code_from_name(props.get("dun", "")) != selected_dun:
            continue
        if (
            selected_pdm_name != "All PDM"
            and props.get("pdm", "") != selected_pdm_name
        ):
            continue
        result.append(feature)
    return result


def make_point_dataframe(features, columns):
    rows = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue
        lon, lat = coordinates[:2]
        props = feature.get("properties", {})
        row = {label: props.get(field, "") for label, field in columns}
        row["Latitude"] = lat
        row["Longitude"] = lon
        rows.append(row)
    return pd.DataFrame(rows)


missing = [str(path) for path in FILES.values() if not path.exists()]
if missing:
    st.error("Missing dashboard data file(s): " + ", ".join(missing))
    st.stop()

datasets = {
    key: read_geojson(str(path), path.stat().st_mtime)
    for key, path in FILES.items()
}

parliament = datasets["parliament"].get("features", [])
duns = datasets["dun"].get("features", [])
pdms = datasets["pdm"].get("features", [])
polling = datasets["polling"].get("features", [])
masjids = datasets["masjid"].get("features", [])
schools = datasets["schools"].get("features", [])
healthcare = datasets["healthcare"].get("features", [])
kampungs = datasets["kampung"].get("features", [])
worship = datasets["worship"].get("features", [])
retail_layers = {
    "99 Speedmart": datasets["speedmart"].get("features", []),
    "KK Mart": datasets["kkmart"].get("features", []),
    "7-Eleven": datasets["seven_eleven"].get("features", []),
    "Pasar Tani": datasets["pasar_tani"].get("features", []),
    "Pasar Pagi": datasets["pasar_pagi"].get("features", []),
}
retail = [
    feature
    for features in retail_layers.values()
    for feature in features
]
# Always derive electoral attributes from the point coordinates. This also
# supports older retail files that used uppercase DUN/PDM property names.
retail = [spatially_assign(feature, duns, pdms) for feature in retail]
roads = datasets["roads"].get("features", [])
vulnerable_raw = datasets["vulnerable"].get("features", [])

# Surau/Musolla are Islamic facilities, but they are not Masjid. Keep them as
# their own dashboard category and remove them from Other houses of worship.
def is_surau(feature):
    props = feature.get("properties", {})
    searchable = " ".join(
        str(props.get(field, ""))
        for field in ("name", "category", "amenity", "religion", "denomination")
    ).casefold()
    return any(term in searchable for term in ("surau", "musolla", "musala"))


suraus = [feature for feature in worship if is_surau(feature)]
worship = [feature for feature in worship if not is_surau(feature)]

# A school can serve two roles. Keep it in the polling-centre layer and also
# include it in the school layer, overview count, Facilities and Data Explorer.
schools = add_school_polling_centres(schools, polling, duns, pdms)

for masjid in masjids:
    geometry = masjid.get("geometry") or {}
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") != "Point" or len(coordinates) < 2:
        continue
    lon, lat = coordinates[:2]
    props = masjid.setdefault("properties", {})
    props["_dun_code"] = next(
        (
            dun_code_from_name(f.get("properties", {}).get("Name", ""))
            for f in duns
            if point_in_geometry(lon, lat, f.get("geometry", {}))
        ),
        None,
    )
    props["_pdm_name"] = next(
        (
            f.get("properties", {}).get("Name", "")
            for f in pdms
            if point_in_geometry(lon, lat, f.get("geometry", {}))
        ),
        "",
    )

vulnerable = []
outside_count = 0
invalid_count = 0

for feature in vulnerable_raw:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates", [])

    if geometry.get("type") != "Point" or len(coordinates) < 2:
        invalid_count += 1
        continue

    lon, lat = coordinates[:2]

    if not point_inside_parliament(lon, lat, parliament):
        outside_count += 1
        continue

vulnerable.append(spatially_assign(feature, duns, pdms))


def line_coordinates(geometry):
    """Return a list of coordinate lines for LineString/MultiLineString."""
    geometry = geometry or {}
    if geometry.get("type") == "LineString":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiLineString":
        return geometry.get("coordinates", [])
    return []


def road_length_km(feature):
    total = 0.0
    for line in line_coordinates(feature.get("geometry")):
        for start, end in zip(line, line[1:]):
            lon1, lat1 = start[:2]
            lon2, lat2 = end[:2]
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = (
                math.sin(dphi / 2) ** 2
                + math.cos(phi1)
                * math.cos(phi2)
                * math.sin(dlambda / 2) ** 2
            )
            total += 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return total


st.title("Parlimen Sepang (P.113) Dashboard")
st.caption("Local information, facilities and issue-monitoring dashboard")

road_df = pd.DataFrame(
    [
        {
            "Road": p.get("road_name", "") or "Unnamed road",
            "Route": p.get("route_number", ""),
            "Road class": p.get("road_class", ""),
            "Responsible authority": p.get("responsible_authority", ""),
            "Maintenance agency": p.get("maintenance_agency", ""),
            "DUN": p.get("dun", ""),
            "PDM": p.get("pdm", ""),
            "Verification": p.get("verification_status", ""),
            "Verification note": p.get("verification_note", ""),
            "Geometry source": p.get("geometry_source", ""),
            "Geometry source URL": p.get("geometry_source_url", ""),
            "Authority reference": p.get("authority_reference", ""),
            "Authority source URL": p.get("authority_source_url", ""),
            "Retrieved": p.get("retrieved_date", ""),
            "_feature_index": index,
        }
        for index, feature in enumerate(roads)
        for p in [feature.get("properties", {})]
    ]
)

overview_tab, map_tab, roads_tab, facilities_tab, issues_tab, data_tab = st.tabs(
    [
        "Overview",
        "Interactive Map",
        "Roads",
        "Facilities",
        "Issues Reported",
        "Data Explorer",
    ]
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
    c9.metric("Surau", len(suraus))

    c10, c11, c12 = st.columns(3)
    c10.metric("Other houses of worship", len(worship))
    c11.metric("Retail & markets", len(retail))
    c12.metric("Vulnerable facilities", len(vulnerable))

    c13, c14, _ = st.columns(3)
    c13.metric(
        "Dialysis centres",
        sum(
            "Dialysis" in f.get("properties", {}).get("category", "")
            for f in vulnerable
        ),
    )

    st.caption(
        "Data presented in this dashboard is compiled from open-source and "
        "publicly available datasets. Figures may differ from official records "
        "because of incomplete coverage, source updates or data availability."
    )

    if outside_count:
        st.warning(
            f"{outside_count} vulnerable-facility record(s) were excluded "
            "because their coordinates are outside the P.113 boundary."
        )

    if invalid_count:
        st.warning(
            f"{invalid_count} vulnerable-facility record(s) were excluded "
            "because they do not contain valid Point geometry."
        )


with map_tab:
    with st.sidebar:
        st.header("Map controls")

        selected_dun_label = st.selectbox(
            "Filter by DUN",
            ["All DUN"] + list(DUN_LABELS.values()),
        )
        selected_dun = next(
            (
                code
                for code, label in DUN_LABELS.items()
                if label == selected_dun_label
            ),
            None,
        )

        pdm_options = [
            f.get("properties", {}).get("Name", "")
            for f in pdms
            if (
                not selected_dun
                or dun_code_from_name(
                    f.get("properties", {}).get("Name", "")
                )
                == selected_dun
            )
        ]

        selected_pdm_name = st.selectbox(
            "Filter by PDM",
            ["All PDM"] + pdm_options,
        )

        st.caption(
            "Use the layer button on the map to turn individual layers on or off."
        )

    visible_pdms = [
        f
        for f in pdms
        if (
            not selected_dun
            or dun_code_from_name(f.get("properties", {}).get("Name", ""))
            == selected_dun
        )
    ]

    if selected_pdm_name != "All PDM":
        visible_pdms = [
            f
            for f in visible_pdms
            if f.get("properties", {}).get("Name", "") == selected_pdm_name
        ]

    visible_polling = []
    for feature in polling:
        values = fields_from_description(
            feature.get("properties", {}).get("description", "")
        )
        code = values.get("Kod Pusat Mengundi", "")

        if selected_dun and f"/{selected_dun}/" not in code:
            continue
        if selected_pdm_name != "All PDM" and code not in selected_pdm_name:
            continue

        visible_polling.append(feature)

    visible_masjids = []
    for feature in masjids:
        props = feature.get("properties", {})

        if selected_dun and props.get("_dun_code") != selected_dun:
            continue
        if (
            selected_pdm_name != "All PDM"
            and props.get("_pdm_name") != selected_pdm_name
        ):
            continue

        visible_masjids.append(feature)

    visible_schools = filter_points(
        schools,
        selected_dun,
        selected_pdm_name,
    )
    visible_healthcare = filter_points(
        healthcare,
        selected_dun,
        selected_pdm_name,
    )
    visible_kampungs = filter_points(
        kampungs,
        selected_dun,
        selected_pdm_name,
    )
    visible_worship = filter_points(
        worship,
        selected_dun,
        selected_pdm_name,
    )
    c14.metric("Road segments", len(roads))
    visible_suraus = filter_points(
        suraus,
        selected_dun,
        selected_pdm_name,
    )
    visible_retail = filter_points(
        retail,
        selected_dun,
        selected_pdm_name,
    )
    visible_vulnerable = filter_points(
        vulnerable,
        selected_dun,
        selected_pdm_name,
    )

    m = folium.Map(
        location=[2.80, 101.67],
        zoom_start=10,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer(
        "OpenStreetMap",
        name="OpenStreetMap",
        show=True,
    ).add_to(m)

    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        show=False,
    ).add_to(m)

    Fullscreen(position="topright").add_to(m)
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqkilometers",
        secondary_area_unit="hectares",
    ).add_to(m)

    parliament_group = folium.FeatureGroup(
        name="Parliament boundary",
        show=True,
    )
    for feature in parliament:
        add_geojson_feature(
            parliament_group,
            feature,
            "#e31a1c",
            4,
            0.0,
            "Parliament",
        )
    parliament_group.add_to(m)

    dun_group = folium.FeatureGroup(
        name="DUN boundaries",
        show=True,
    )
    for feature in duns:
        code = (
            dun_code_from_name(
                feature.get("properties", {}).get("Name", "")
            )
            or "55"
        )
        if not selected_dun or code == selected_dun:
            add_geojson_feature(
                dun_group,
                feature,
                DUN_COLORS[code],
                4,
                0.06,
                "DUN",
            )
    dun_group.add_to(m)

    pdm_group = folium.FeatureGroup(
        name="PDM boundaries",
        show=True,
    )
    for feature in visible_pdms:
        code = (
            dun_code_from_name(
                feature.get("properties", {}).get("Name", "")
            )
            or "55"
        )
        add_geojson_feature(
            pdm_group,
            feature,
            DUN_COLORS[code],
            2,
            0.12,
            "PDM",
        )
    pdm_group.add_to(m)

    polling_group = folium.FeatureGroup(
        name="Polling centres",
        show=True,
    )
    for feature in visible_polling:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        values = fields_from_description(props.get("description", ""))
        lon, lat = coordinates[:2]

        details = "".join(
            f"<b>{label}:</b> {values.get(field, '')}<br>"
            for field, label in [
                ("Kod Pusat Mengundi", "Code"),
                ("Nama DUN", "DUN"),
                ("Pusat Mengundi", "Polling centre"),
                ("Latitude", "Latitude"),
                ("Longitude", "Longitude"),
            ]
        )

        folium.CircleMarker(
            [lat, lon],
            radius=6,
            color="#9a3412",
            weight=2,
            fill=True,
            fill_color="#fb923c",
            fill_opacity=0.95,
            tooltip=props.get("Name", "Polling centre"),
            popup=folium.Popup(
                f"<b>{props.get('Name', '')}</b><br><br>{details}",
                max_width=400,
            ),
        ).add_to(polling_group)

    polling_group.add_to(m)

    masjid_group = folium.FeatureGroup(name="Masjid", show=True)
    for feature in visible_masjids:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]

        popup = (
            f"<b>{props.get('Field3', 'Masjid')}</b><br><br>"
            f"<b>District:</b> {props.get('Field1', '')}<br>"
            f"<b>Mukim:</b> {props.get('Field2', '')}<br>"
            f"<b>Address:</b> {props.get('Field4', '')}<br>"
            f"<b>PDM:</b> {props.get('_pdm_name', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34),
                icon_anchor=(17, 17),
                html=(
                    "<div style='width:34px;height:34px;border-radius:50%;"
                    "background:#15803d;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    "font-size:20px'>🕌</div>"
                ),
            ),
            tooltip=props.get("Field3", "Masjid"),
            popup=folium.Popup(popup, max_width=430),
        ).add_to(masjid_group)

    masjid_group.add_to(m)

    school_group = folium.FeatureGroup(
        name="Schools",
        show=True,
    )
    for feature in visible_schools:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]

        popup = (
            f"<b>{props.get('name', 'School')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34),
                icon_anchor=(17, 17),
                html=(
                    "<div style='width:34px;height:34px;border-radius:50%;"
                    "background:#1d4ed8;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    "font-size:20px'>🏫</div>"
                ),
            ),
            tooltip=props.get("name", "School"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(school_group)

    school_group.add_to(m)

    healthcare_group = folium.FeatureGroup(
        name="Healthcare",
        show=True,
    )
    for feature in visible_healthcare:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]

        popup = (
            f"<b>{props.get('name', 'Healthcare facility')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Phone:</b> {props.get('phone', '')}<br>"
            f"<b>Opening hours:</b> {props.get('opening_hours', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        is_hospital = props.get("category") == "Hospital"
        marker_color = "#dc2626" if is_hospital else "#0891b2"
        marker_icon = "🏥" if is_hospital else "✚"

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34),
                icon_anchor=(17, 17),
                html=(
                    f"<div style='width:34px;height:34px;border-radius:50%;"
                    f"background:{marker_color};color:white;"
                    "border:2px solid white;box-shadow:0 1px 5px #333;"
                    "display:flex;align-items:center;justify-content:center;"
                    f"font-size:19px;font-weight:bold'>{marker_icon}</div>"
                ),
            ),
            tooltip=props.get("name", "Healthcare facility"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(healthcare_group)

    healthcare_group.add_to(m)

    kampung_group = folium.FeatureGroup(
        name="Kampung",
        show=True,
    )
    for feature in visible_kampungs:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]

        popup = (
            f"<b>{props.get('name', 'Kampung')}</b><br><br>"
            f"<b>Type:</b> {props.get('kampung_type', '')}<br>"
            f"<b>District:</b> {props.get('district', '')}<br>"
            f"<b>Mukim:</b> {props.get('mukim', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Area:</b> {props.get('area_ha', '')} ha<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(34, 34),
                icon_anchor=(17, 17),
                html=(
                    "<div style='width:34px;height:34px;border-radius:50%;"
                    "background:#7c3aed;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    "font-size:19px'>🏘️</div>"
                ),
            ),
            tooltip=props.get("name", "Kampung"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(kampung_group)

    kampung_group.add_to(m)

    surau_group = folium.FeatureGroup(
        name="Surau",
        show=True,
    )

    for feature in visible_suraus:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]
        popup = (
            f"<b>{props.get('name', 'Surau')}</b><br><br>"
            f"<b>Category:</b> Surau / Musolla<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(32, 32),
                icon_anchor=(16, 16),
                html=(
                    "<div style='width:32px;height:32px;border-radius:50%;"
                    "background:#059669;color:white;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    "font-size:18px'>☪</div>"
                ),
            ),
            tooltip=props.get("name", "Surau"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(surau_group)

    surau_group.add_to(m)

    worship_group = folium.FeatureGroup(
        name="Other houses of worship",
        show=False,
    )
    worship_icons = {
        "Church": "✝",
        "Hindu Temple": "🛕",
        "Buddhist Temple": "☸",
        "Chinese / Taoist Temple": "🏮",
        "Gurdwara": "☬",
    }

    for feature in visible_worship:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]
        icon = worship_icons.get(props.get("category"), "◆")

        popup = (
            f"<b>{props.get('name', '')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>Religion:</b> {props.get('religion', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(32, 32),
                icon_anchor=(16, 16),
                html=(
                    "<div style='width:32px;height:32px;border-radius:50%;"
                    "background:#a16207;color:white;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    f"font-size:18px'>{icon}</div>"
                ),
            ),
            tooltip=props.get("name", "House of worship"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(worship_group)

    worship_group.add_to(m)

    retail_group = folium.FeatureGroup(
        name="Retail & markets",
        show=False,
    )
    for feature in visible_retail:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]
        icon = "🧺" if props.get("group") == "Market" else "🛒"

        popup = (
            f"<b>{props.get('name', '')}</b><br><br>"
            f"<b>Category:</b> {props.get('category', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Opening hours:</b> {props.get('opening_hours', '')}<br>"
            f"<b>Premises:</b> {props.get('premises_type', '')}<br>"
            f"<b>Status:</b> {props.get('verification_status', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(32, 32),
                icon_anchor=(16, 16),
                html=(
                    "<div style='width:32px;height:32px;border-radius:50%;"
                    "background:#be123c;border:2px solid white;"
                    "box-shadow:0 1px 5px #333;display:flex;"
                    "align-items:center;justify-content:center;"
                    f"font-size:17px'>{icon}</div>"
                ),
            ),
            tooltip=props.get("name", "Retail / market"),
            popup=folium.Popup(popup, max_width=440),
        ).add_to(retail_group)

    retail_group.add_to(m)

    vulnerable_group = folium.FeatureGroup(
        name="Vulnerable facilities",
        show=False,
    )

    for feature in visible_vulnerable:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        props = feature.get("properties", {})
        lon, lat = coordinates[:2]
        category = props.get("category", "")
        icon = VULNERABLE_ICONS.get(category, "◆")
        marker_color = VULNERABLE_COLORS.get(category, "#475569")

        popup = (
            f"<b>{props.get('name', 'Vulnerable facility')}</b><br><br>"
            f"<b>Category:</b> {category}<br>"
            f"<b>Operator:</b> {props.get('operator', '')}<br>"
            f"<b>Resident/patient group:</b> "
            f"{props.get('resident_group', '')}<br>"
            f"<b>Capacity:</b> {props.get('capacity', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Address:</b> {props.get('address', '')}<br>"
            f"<b>Phone:</b> {props.get('phone', '')}<br>"
            f"<b>Opening hours:</b> "
            f"{props.get('opening_hours', '')}<br>"
            f"<b>Emergency contact:</b> "
            f"{props.get('emergency_contact', '')}<br>"
            f"<b>Wheelchair access:</b> "
            f"{props.get('wheelchair_access', '')}<br>"
            f"<b>Backup power:</b> {props.get('backup_power', '')}<br>"
            f"<b>Flood-risk note:</b> "
            f"{props.get('flood_risk_note', '')}<br>"
            f"<b>Evacuation support:</b> "
            f"{props.get('evacuation_support', '')}<br>"
            f"<b>Dialysis type:</b> "
            f"{props.get('dialysis_type', '')}<br>"
            f"<b>Sessions per day:</b> "
            f"{props.get('sessions_per_day', '')}<br>"
            f"<b>Verification:</b> "
            f"{props.get('verification_status', '')}<br>"
            f"<b>Last verified:</b> "
            f"{props.get('last_verified', '')}<br>"
            f"<b>Source:</b> {props.get('source', '')}<br>"
            f"<b>Latitude:</b> {lat}<br>"
            f"<b>Longitude:</b> {lon}"
        )

        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                icon_size=(36, 36),
                icon_anchor=(18, 18),
                html=(
                    f"<div style='width:36px;height:36px;border-radius:50%;"
                    f"background:{marker_color};color:white;"
                    "border:2px solid white;box-shadow:0 1px 5px #333;"
                    "display:flex;align-items:center;justify-content:center;"
                    f"font-size:19px'>{icon}</div>"
                ),
            ),
            tooltip=props.get("name", "Vulnerable facility"),
            popup=folium.Popup(popup, max_width=480),
        ).add_to(vulnerable_group)

    vulnerable_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(
        m,
        use_container_width=True,
        height=680,
        returned_objects=[],
    )


with roads_tab:
    st.subheader("Roads and Responsible Authorities")
    st.caption(
        "Filter the road list, then click a row to highlight that road on the map. "
        "Use the ruler button on the map to measure any distance or area."
    )

    shown_roads = road_df.copy()
    c1, c2, c3 = st.columns(3)
    with c1:
        road_dun = st.selectbox(
            "DUN",
            ["All DUN"]
            + sorted(shown_roads["DUN"].dropna().loc[lambda s: s != ""].unique()),
            key="roads_dun",
        )
    if road_dun != "All DUN":
        shown_roads = shown_roads[shown_roads["DUN"] == road_dun]

    with c2:
        road_pdm = st.selectbox(
            "PDM",
            ["All PDM"]
            + sorted(shown_roads["PDM"].dropna().loc[lambda s: s != ""].unique()),
            key="roads_pdm",
        )
    if road_pdm != "All PDM":
        shown_roads = shown_roads[shown_roads["PDM"] == road_pdm]

    with c3:
        road_class_filter = st.selectbox(
            "Road class",
            ["All classes"]
            + sorted(
                shown_roads["Road class"]
                .dropna()
                .loc[lambda s: s != ""]
                .unique()
            ),
            key="roads_class",
        )
    if road_class_filter != "All classes":
        shown_roads = shown_roads[
            shown_roads["Road class"] == road_class_filter
        ]

    road_query = st.text_input(
        "Search road name, route, authority or verification status",
        key="roads_search",
    )
    if road_query:
        searchable = shown_roads.drop(columns=["_feature_index"])
        shown_roads = shown_roads[
            searchable.astype(str).apply(
                lambda row: row.str.contains(
                    road_query, case=False, na=False, regex=False
                ).any(),
                axis=1,
            )
        ]

    st.metric("Road segments shown", f"{len(shown_roads):,} of {len(roads):,}")
    table_columns = [
        "Road",
        "Route",
        "Road class",
        "Responsible authority",
        "Maintenance agency",
        "DUN",
        "PDM",
        "Verification",
    ]
    road_event = st.dataframe(
        shown_roads[table_columns],
        use_container_width=True,
        hide_index=True,
        height=330,
        selection_mode="single-row",
        on_select="rerun",
        key="road_list",
    )

    selected_feature_index = None
    selected_rows = road_event.selection.rows
    if selected_rows and selected_rows[0] < len(shown_roads):
        selected_feature_index = int(
            shown_roads.iloc[selected_rows[0]]["_feature_index"]
        )

    show_filtered = st.checkbox(
        "Load all filtered roads on map (may be slower for a large result)",
        value=False,
        key="show_filtered_roads",
    )

    road_map = folium.Map(
        location=[2.80, 101.67],
        zoom_start=10,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        show=False,
    ).add_to(road_map)
    Fullscreen(position="topright").add_to(road_map)
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqkilometers",
        secondary_area_unit="hectares",
    ).add_to(road_map)

    road_colors = {
        "Expressway": "#7c3aed",
        "Federal Road": "#dc2626",
        "State Road": "#f59e0b",
        "Major road—authority unverified": "#475569",
        "Local/other road": "#64748b",
    }
    map_indices = (
        shown_roads["_feature_index"].astype(int).tolist()
        if show_filtered
        else ([] if selected_feature_index is None else [selected_feature_index])
    )
    selected_bounds = []
    for feature_index in map_indices:
        feature = roads[feature_index]
        props = feature.get("properties", {})
        road_class = props.get("road_class", "Unverified")
        is_selected = feature_index == selected_feature_index
        length_km = road_length_km(feature)
        popup = (
            f"<b>{props.get('road_name') or 'Unnamed road'}</b><br><br>"
            f"<b>Route:</b> {props.get('route_number', '')}<br>"
            f"<b>Mapped segment length:</b> {length_km:.3f} km<br>"
            f"<b>Road class:</b> {road_class}<br>"
            f"<b>Responsible authority:</b> "
            f"{props.get('responsible_authority', '')}<br>"
            f"<b>Maintenance agency:</b> "
            f"{props.get('maintenance_agency', '')}<br>"
            f"<b>DUN:</b> {props.get('dun', '')}<br>"
            f"<b>PDM:</b> {props.get('pdm', '')}<br>"
            f"<b>Verification:</b> "
            f"{props.get('verification_status', '')}<br>"
            f"<b>Geometry source:</b> {props.get('geometry_source', '')}<br>"
            f"<b>Retrieved:</b> {props.get('retrieved_date', '')}"
        )
        color = "#00e5ff" if is_selected else road_colors.get(
            road_class, "#475569"
        )
        folium.GeoJson(
            feature,
            style_function=lambda _, color=color, selected=is_selected: {
                "color": color,
                "weight": 7 if selected else 3,
                "opacity": 1.0 if selected else 0.75,
            },
            tooltip=props.get("road_name") or road_class,
            popup=folium.Popup(popup, max_width=500),
        ).add_to(road_map)
        if is_selected:
            for line in line_coordinates(feature.get("geometry")):
                selected_bounds.extend([[coord[1], coord[0]] for coord in line])

    if selected_bounds:
        road_map.fit_bounds(selected_bounds, padding=(25, 25))
        selected_feature = roads[selected_feature_index]
        selected_props = selected_feature.get("properties", {})
        st.success(
            f"Selected: {selected_props.get('road_name') or 'Unnamed road'} "
            f"— mapped segment length {road_length_km(selected_feature):.3f} km"
        )
    elif not show_filtered:
        st.info("Select one road from the table to display and highlight it.")

    folium.LayerControl(collapsed=True).add_to(road_map)
    st_folium(
        road_map,
        use_container_width=True,
        height=620,
        returned_objects=[],
        key="roads_map",
    )


with facilities_tab:
    st.subheader("Facilities")

    facility_rows = []
    for feature in masjids:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        lon, lat = coordinates[:2]
        props = feature.get("properties", {})

        facility_rows.append(
            {
                "Masjid": props.get("Field3", ""),
                "District": props.get("Field1", ""),
                "Mukim": props.get("Field2", ""),
                "DUN": DUN_LABELS.get(props.get("_dun_code"), ""),
                "PDM": props.get("_pdm_name", ""),
                "Address": props.get("Field4", ""),
                "Latitude": lat,
                "Longitude": lon,
            }
        )

    facility_df = pd.DataFrame(facility_rows)

    school_df = make_point_dataframe(
        schools,
        [
            ("School", "name"),
            ("Category", "category"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Verification", "verification_status"),
        ],
    )

    healthcare_df = make_point_dataframe(
        healthcare,
        [
            ("Facility", "name"),
            ("Category", "category"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Phone", "phone"),
            ("Opening hours", "opening_hours"),
            ("Verification", "verification_status"),
        ],
    )

    kampung_df = make_point_dataframe(
        kampungs,
        [
            ("Kampung", "name"),
            ("Type", "kampung_type"),
            ("District", "district"),
            ("Mukim", "mukim"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Area (ha)", "area_ha"),
            ("Verification", "verification_status"),
        ],
    )

    worship_df = make_point_dataframe(
        worship,
        [
            ("Name", "name"),
            ("Category", "category"),
            ("Religion", "religion"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Verification", "verification_status"),
        ],
    )

    surau_df = make_point_dataframe(
        suraus,
        [
            ("Surau", "name"),
            ("Category", "category"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Verification", "verification_status"),
        ],
    )

    retail_df = make_point_dataframe(
        retail,
        [
            ("Name", "name"),
            ("Group", "group"),
            ("Category", "category"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Opening hours", "opening_hours"),
            ("Premises", "premises_type"),
            ("Verification", "verification_status"),
        ],
    )

    vulnerable_df = make_point_dataframe(
        vulnerable,
        [
            ("Name", "name"),
            ("Category", "category"),
            ("Operator", "operator"),
            ("Resident/patient group", "resident_group"),
            ("Capacity", "capacity"),
            ("DUN", "dun"),
            ("PDM", "pdm"),
            ("Address", "address"),
            ("Postcode", "postcode"),
            ("Phone", "phone"),
            ("Email", "email"),
            ("Website", "website"),
            ("Opening hours", "opening_hours"),
            ("Emergency contact", "emergency_contact"),
            ("Wheelchair access", "wheelchair_access"),
            ("Backup power", "backup_power"),
            ("Flood-risk note", "flood_risk_note"),
            ("Evacuation support", "evacuation_support"),
            ("Dialysis type", "dialysis_type"),
            ("Sessions per day", "sessions_per_day"),
            ("Verification", "verification_status"),
            ("Last verified", "last_verified"),
            ("Source", "source"),
            ("Remarks", "remarks"),
        ],
    )

    facility_type = st.selectbox(
        "Facility category",
        [
            "Select a category",
            "Masjid",
            "Surau",
            "Other houses of worship",
            "Schools",
            "Healthcare",
            "Kampung",
            "Retail & Markets",
            "Vulnerable Facilities",
        ],
    )

    if facility_type == "Select a category":
        st.info("Choose a facility category above.")

    elif facility_type == "Masjid":
        shown = facility_df.copy()

        c1, c2 = st.columns(2)
        with c1:
            selected_dun2 = st.selectbox(
                "Filter by DUN",
                ["All DUN"]
                + sorted(
                    shown["DUN"]
                    .dropna()
                    .loc[lambda series: series != ""]
                    .unique()
                    .tolist()
                ),
                key="facility_masjid_dun",
            )
        if selected_dun2 != "All DUN":
            shown = shown[shown["DUN"] == selected_dun2]

        with c2:
            selected_pdm2 = st.selectbox(
                "Filter by PDM",
                ["All PDM"]
                + sorted(
                    shown["PDM"]
                    .dropna()
                    .loc[lambda series: series != ""]
                    .unique()
                    .tolist()
                ),
                key="facility_masjid_pdm",
            )
        if selected_pdm2 != "All PDM":
            shown = shown[shown["PDM"] == selected_pdm2]

        query = st.text_input(
            "Search by masjid name, mukim, address, DUN or PDM"
        )
        if query:
            shown = shown[
                shown.astype(str).apply(
                    lambda row: row.str.contains(
                        query,
                        case=False,
                        na=False,
                    ).any(),
                    axis=1,
                )
            ]

        st.metric("Masjid shown", f"{len(shown)} of {len(masjids)}")
        st.dataframe(
            shown,
            use_container_width=True,
            hide_index=True,
            height=520,
        )

    elif facility_type == "Vulnerable Facilities":
        shown = vulnerable_df.copy()

        if shown.empty:
            st.info(
                "No vulnerable-facility records are currently stored. "
                "Add verified Point features to "
                "data/vulnerable_facilities.geojson."
            )
        else:
            c1, c2, c3 = st.columns(3)

            with c1:
                selected_dun2 = st.selectbox(
                    "Filter by DUN",
                    ["All DUN"]
                    + sorted(
                        shown["DUN"]
                        .dropna()
                        .loc[lambda series: series != ""]
                        .unique()
                        .tolist()
                    ),
                    key="vulnerable_dun",
                )

            if selected_dun2 != "All DUN":
                shown = shown[shown["DUN"] == selected_dun2]

            with c2:
                selected_pdm2 = st.selectbox(
                    "Filter by PDM",
                    ["All PDM"]
                    + sorted(
                        shown["PDM"]
                        .dropna()
                        .loc[lambda series: series != ""]
                        .unique()
                        .tolist()
                    ),
                    key="vulnerable_pdm",
                )

            if selected_pdm2 != "All PDM":
                shown = shown[shown["PDM"] == selected_pdm2]

            with c3:
                selected_category2 = st.selectbox(
                    "Facility type",
                    ["All categories"]
                    + sorted(
                        shown["Category"]
                        .dropna()
                        .loc[lambda series: series != ""]
                        .unique()
                        .tolist()
                    ),
                    key="vulnerable_category",
                )

            if selected_category2 != "All categories":
                shown = shown[shown["Category"] == selected_category2]

            query = st.text_input(
                "Search by name, category, operator, address, DUN or PDM"
            )

            if query:
                shown = shown[
                    shown.astype(str).apply(
                        lambda row: row.str.contains(
                            query,
                            case=False,
                            na=False,
                        ).any(),
                        axis=1,
                    )
                ]

            st.metric(
                "Vulnerable facilities shown",
                f"{len(shown)} of {len(vulnerable)}",
            )

            st.dataframe(
                shown,
                use_container_width=True,
                hide_index=True,
                height=520,
            )

            st.caption(
                "Only facilities located inside the P.113 boundary are shown. "
                "Do not publish names, health records or personal details of "
                "residents, children or patients."
            )

    else:
        source_map = {
            "Surau": surau_df,
            "Other houses of worship": worship_df,
            "Schools": school_df,
            "Healthcare": healthcare_df,
            "Kampung": kampung_df,
            "Retail & Markets": retail_df,
        }

        shown = source_map[facility_type].copy()

        if shown.empty:
            st.info("No records are available for this category.")
        else:
            c1, c2 = st.columns(2)

            with c1:
                selected_dun2 = st.selectbox(
                    "Filter by DUN",
                    ["All DUN"]
                    + sorted(
                        shown["DUN"]
                        .dropna()
                        .loc[lambda series: series != ""]
                        .unique()
                        .tolist()
                    ),
                    key=f"{facility_type}_dun",
                )

            if selected_dun2 != "All DUN":
                shown = shown[shown["DUN"] == selected_dun2]

            with c2:
                selected_pdm2 = st.selectbox(
                    "Filter by PDM",
                    ["All PDM"]
                    + sorted(
                        shown["PDM"]
                        .dropna()
                        .loc[lambda series: series != ""]
                        .unique()
                        .tolist()
                    ),
                    key=f"{facility_type}_pdm",
                )

            if selected_pdm2 != "All PDM":
                shown = shown[shown["PDM"] == selected_pdm2]

            query = st.text_input(
                f"Search {facility_type.lower()}",
                key=f"{facility_type}_query",
            )

            if query:
                shown = shown[
                    shown.astype(str).apply(
                        lambda row: row.str.contains(
                            query,
                            case=False,
                            na=False,
                        ).any(),
                        axis=1,
                    )
                ]

            st.metric(
                f"{facility_type} shown",
                len(shown),
            )

            st.dataframe(
                shown,
                use_container_width=True,
                hide_index=True,
                height=520,
            )


with issues_tab:
    st.subheader("Issues Reported")
    st.info(
        "This section is ready for a future issues dataset, including "
        "category, description, location, date, status, responsible agency "
        "and follow-up action."
    )


with data_tab:
    st.subheader("Data Explorer")

    polling_rows = []
    for feature in polling:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        values = fields_from_description(
            feature.get("properties", {}).get("description", "")
        )
        lon, lat = coordinates[:2]

        polling_rows.append(
            {
                "PDM": feature.get("properties", {}).get("Name", ""),
                "Code": values.get("Kod Pusat Mengundi", ""),
                "DUN": values.get("Nama DUN", ""),
                "Polling centre": values.get("Pusat Mengundi", ""),
                "Latitude": lat,
                "Longitude": lon,
            }
        )

    polling_df = pd.DataFrame(polling_rows)

    dataset_name = st.selectbox(
        "Dataset",
        [
            "Polling centres",
            "Masjid",
            "Surau",
            "Other houses of worship",
            "Schools",
            "Healthcare",
            "Kampung",
            "Retail & Markets",
            "Roads & Authorities",
            "Vulnerable Facilities",
        ],
    )

    dataset_map = {
        "Polling centres": polling_df,
        "Masjid": facility_df,
        "Surau": surau_df,
        "Other houses of worship": worship_df,
        "Schools": school_df,
        "Healthcare": healthcare_df,
        "Kampung": kampung_df,
        "Retail & Markets": retail_df,
        "Roads & Authorities": road_df,
        "Vulnerable Facilities": vulnerable_df,
    }

    selected_df = dataset_map[dataset_name]

    st.caption(
        f"{len(selected_df)} record(s) are available in this dataset."
    )
    st.dataframe(
        selected_df,
        use_container_width=True,
        hide_index=True,
    )
