"""Mappa dei prezzi carburanti della provincia di Latina (fonte MIMIT)."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from html import escape
from pathlib import Path
import ssl
import re

import folium
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium


st.set_page_config(page_title="Carburanti · Provincia di Latina", page_icon="⛽", layout="wide")

PRICES_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
STATIONS_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
SOURCE_URL = "https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti"
HEADERS = {"User-Agent": "MappaCarburantiLatina/1.0 (open-data MIMIT)"}


class WindowsCertificateAdapter(HTTPAdapter):
    """Use Windows' trusted certificate store while keeping TLS verification on."""

    def __init__(self, *args, **kwargs):
        self.ssl_context = ssl.create_default_context()
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


HTTP = requests.Session()
if __import__("os").name == "nt":
    HTTP.mount("https://", WindowsCertificateAdapter())


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]
    return df


def parse_csv(raw: str, source: str) -> tuple[pd.DataFrame, str | None]:
    # Il file MIMIT inizia con una riga informativa e poi con l'intestazione.
    lines = raw.splitlines()
    header_line = next((i for i, line in enumerate(lines) if "idImpianto" in line), None)
    if header_line is None:
        raise ValueError(f"Intestazione CSV non riconosciuta in {source}")
    extracted = None
    for line in lines[:header_line]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
        if m:
            extracted = m.group(1)
            break
    df = pd.read_csv(StringIO("\n".join(lines[header_line:])), sep="|", dtype=str, on_bad_lines="skip")
    return normalize_columns(df), extracted


def read_cached_csv(filename: str) -> tuple[pd.DataFrame, str | None]:
    path = Path(__file__).parent / filename
    if not path.is_file():
        raise FileNotFoundError(f"Cache dati MIMIT non trovata: {path}")
    return parse_csv(path.read_text(encoding="utf-8-sig", errors="replace"), str(path))


def col(df: pd.DataFrame, *names: str) -> str:
    # Il MIMIT talvolta pubblica intestazioni con spazi ("Nome Impianto")
    # e talvolta in forma compatta ("NomeImpianto").
    by_lower = {re.sub(r"[^a-z0-9]", "", str(c).strip().lower()): c for c in df.columns}
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.strip().lower())
        if key in by_lower:
            return by_lower[key]
    raise ValueError(f"Colonna mancante ({', '.join(names)}). Colonne ricevute: {', '.join(map(str, df.columns))}")


@st.cache_data(ttl=0, show_spinner=False)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, str, datetime]:
    # La cache viene aggiornata ogni giorno dal workflow GitHub scaricando i
    # CSV ufficiali. Leggendola localmente evitiamo timeout MIMIT su Streamlit.
    stations, station_date = read_cached_csv("anagrafica_impianti_attivi.csv")
    prices, price_date = read_cached_csv("prezzo_alle_8.csv")
    sid, pid = col(stations, "idImpianto"), col(prices, "idImpianto")
    stations = stations.rename(columns={sid: "id"})
    prices = prices.rename(columns={pid: "id"})
    data = prices.merge(stations, on="id", how="inner", suffixes=("_prezzo", "_impianto"))

    fuel_col = col(data, "descCarburante")
    price_col = col(data, "prezzo")
    self_col = col(data, "isSelf")
    date_col = col(data, "dtComu")
    name_col = col(data, "NomeImpianto")
    brand_col = col(data, "Bandiera")
    address_col = col(data, "Indirizzo")
    town_col = col(data, "Comune")
    province_col = col(data, "Provincia")
    lat_col = col(data, "Latitudine")
    lon_col = col(data, "Longitudine")

    data["prezzo_num"] = pd.to_numeric(data[price_col].str.replace(",", ".", regex=False), errors="coerce")
    data["lat"] = pd.to_numeric(data[lat_col].str.replace(",", ".", regex=False), errors="coerce")
    data["lon"] = pd.to_numeric(data[lon_col].str.replace(",", ".", regex=False), errors="coerce")
    data["data_comunicazione"] = pd.to_datetime(data[date_col], errors="coerce", dayfirst=True)
    raw_fuel = data[fuel_col].fillna("").str.strip().str.casefold()
    # Mostra soltanto le due categorie standard; le varianti premium/speciali
    # presenti nel dataset MIMIT restano fuori.
    data["carburante_originale"] = data[fuel_col].fillna("").str.strip()
    data["carburante"] = raw_fuel.map({"benzina": "Benzina", "gasolio": "Gasolio"})
    data["modalita"] = data[self_col].map(lambda x: "Self" if str(x).strip() in ("1", "1.0", "True") else "Servito")
    data["impianto"] = data[name_col].fillna("").str.strip()
    data["bandiera"] = data[brand_col].fillna("").str.strip()
    data["indirizzo"] = data[address_col].fillna("").str.strip()
    data["comune"] = data[town_col].fillna("").str.strip()
    data["provincia"] = data[province_col].fillna("").str.strip().str.upper()
    data = data[data["provincia"].isin(["LATINA", "LT"])].copy()
    data = data[data["prezzo_num"].notna()]
    all_prices = data.copy()
    data = data[data["lat"].between(40.7, 42.0) & data["lon"].between(12.4, 14.2)]
    data = data[data["carburante"].notna()]
    extracted = price_date or station_date or "non indicata"
    return data, all_prices, extracted, datetime.now()


st.title("⛽ Carburanti nella provincia di Latina")
st.caption("Mappa e prezzi comunicati dai gestori all’Osservatorio Prezzi Carburanti del MIMIT.")

with st.spinner("Scarico i dati ufficiali più recenti dal MIMIT…"):
    try:
        data, all_prices, extracted, fetched_at = load_data()
    except requests.exceptions.SSLError as exc:
        st.error("Connessione HTTPS al MIMIT non verificabile: Python non riconosce il certificato del sito. Ho configurato l’app per usare i certificati attendibili di Windows; riavvia l’app se questo messaggio resta visibile.")
        st.code(str(exc))
        st.markdown(f"[Apri la fonte ufficiale MIMIT]({SOURCE_URL})")
        st.stop()
    except requests.exceptions.ConnectionError as exc:
        st.error("Il computer non riesce a raggiungere il sito MIMIT. Controlla la connessione Internet o eventuali proxy/firewall, poi ricarica la pagina.")
        st.code(str(exc))
        st.markdown(f"[Apri la fonte ufficiale MIMIT]({SOURCE_URL})")
        st.stop()
    except Exception as exc:
        st.error("Non riesco a scaricare o leggere i dati ufficiali del MIMIT in questo momento.")
        st.code(str(exc))
        st.markdown(f"[Apri la fonte ufficiale MIMIT]({SOURCE_URL})")
        st.stop()

if data.empty:
    st.warning("Il dataset aggiornato non contiene impianti con prezzi e coordinate valide per la provincia di Latina.")
    st.stop()

with st.sidebar:
    st.header("Filtri")
    fuel_options = [fuel for fuel in ["Benzina", "Gasolio"] if fuel in set(data["carburante"])]
    selected_fuels = st.multiselect("Carburante", fuel_options, default=fuel_options)
    st.caption("Prezzi in modalità servito; il self-service è escluso.")
    max_age = st.slider("Mostra prezzi comunicati negli ultimi (giorni)", 1, 30, 14)
    st.caption("Imposta 30 giorni per includere tutti i prezzi comunicati nel mese.")

view = data[data["carburante"].isin(selected_fuels) & (data["modalita"] == "Servito")].copy()
cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=max_age)
view = view[view["data_comunicazione"].isna() | (view["data_comunicazione"] >= cutoff)]

search_col, info_col = st.columns([2, 1])
with search_col:
    town_query = st.text_input("Cerca un comune", placeholder="Es. Priverno, Sonnino o Terracina")
if town_query.strip():
    view = view[view["comune"].str.contains(re.escape(town_query.strip()), case=False, na=False, regex=True)]
with info_col:
    st.caption("Mappa e tabelle seguono i filtri selezionati.")

target_towns = {"PRIVERNO", "SONNINO", "TERRACINA"}
# Eccezione richiesta: il Tamoil di Sonnino Scalo compare sempre, anche se i
# filtri correnti escludono carburante, modalità, ricerca per comune o data.
station_text = all_prices[["comune", "indirizzo", "impianto"]].fillna("").agg(" ".join, axis=1)
is_sonnino_station = station_text.str.contains("sonnino", case=False, na=False)
# Nell'anagrafica MIMIT questa pompa può essere identificata come "4814" e
# "SP Sonninese km 0,45", mentre il locator ufficiale Tamoil la chiama Tamoil 4814.
is_tamoil = all_prices["bandiera"].str.contains("tamoil", case=False, na=False) | all_prices["impianto"].str.contains("tamoil", case=False, na=False)
is_4814 = station_text.str.contains(r"\b4814\b", case=False, na=False, regex=True)
is_sonninese = station_text.str.contains("sonninese", case=False, na=False)
tamoil_sonnino = all_prices[(is_tamoil & is_sonnino_station) | (is_4814 & is_sonnino_station) | (is_sonninese & is_sonnino_station)].copy()
tamoil_sonnino = tamoil_sonnino[tamoil_sonnino["carburante"].notna()]
if not tamoil_sonnino.empty:
    tamoil_sonnino["bandiera"] = "Tamoil"
    tamoil_sonnino["impianto"] = "Tamoil 4814 · Sonnino Scalo"

featured = view[view["comune"].str.strip().str.upper().isin(target_towns)].copy()
featured["fuori_filtri"] = ""
if not tamoil_sonnino.empty:
    existing = set(zip(featured["id"].astype(str), featured["carburante"], featured["modalita"]))
    extra_featured = tamoil_sonnino[
        ~tamoil_sonnino.apply(lambda row: (str(row["id"]), row["carburante"], row["modalita"]) in existing, axis=1)
    ].copy()
    extra_featured["fuori_filtri"] = "Sì · fuori filtri"
    featured = pd.concat([featured, extra_featured], ignore_index=True)

map_view = view.copy()
map_view["fuori_filtri"] = ""
if not tamoil_sonnino.empty:
    shown = set(zip(map_view["id"].astype(str), map_view["carburante"], map_view["modalita"]))
    extra_map = tamoil_sonnino[
        ~tamoil_sonnino.apply(lambda row: (str(row["id"]), row["carburante"], row["modalita"]) in shown, axis=1)
    ].copy()
    extra_map["fuori_filtri"] = "Sì · fuori filtri"
    map_view = pd.concat([map_view, extra_map], ignore_index=True)

c1, c2, c3 = st.columns(3)
c1.metric("Impianti sulla mappa", f"{map_view['id'].nunique():,}".replace(",", "."))
c2.metric("Prezzo minimo mostrato", f"€ {view['prezzo_num'].min():.3f}/L" if not view.empty else "—")
c3.metric("Estrazione MIMIT", extracted)
st.info("I prezzi sono quelli dichiarati dai gestori: il file open data fotografa i valori delle ore 8 del giorno precedente alla pubblicazione. L’aggiornamento del file non garantisce che ogni prezzo dichiarato sia ancora quello esposto alla pompa. Controlla la data di comunicazione nella scheda.")

if map_view.empty:
    st.warning("Nessun risultato con questi filtri e il Tamoil di Sonnino Scalo non compare nei prezzi MIMIT disponibili.")
    st.stop()
if view.empty:
    st.info("Nessun altro distributore corrisponde ai filtri; sulla mappa e nella classifica resta visibile il Tamoil di Sonnino Scalo richiesto.")

center = [float(map_view["lat"].median()), float(map_view["lon"].median())]
m = folium.Map(location=center, zoom_start=9, tiles="OpenStreetMap", control_scale=True)
cluster = MarkerCluster(name="Distributori").add_to(m)
for _, row in map_view.iterrows():
    age = "Data comunicazione non disponibile"
    if pd.notna(row["data_comunicazione"]):
        age = "Prezzo comunicato " + row["data_comunicazione"].strftime("%d/%m/%Y")
    supplier = escape(str(row["bandiera"] or row["impianto"] or "?"))
    out_of_filter = bool(row.get("fuori_filtri", ""))
    popup = (f"<b>{supplier}</b><br>{escape(str(row['indirizzo']))}, {escape(str(row['comune']))}<br>"
             f"{escape(str(row['carburante']))} · {escape(str(row['modalita']))}: <b>€ {row['prezzo_num']:.3f}/L</b><br>{age}"
             f"{'<br><b>Incluso fuori dai filtri</b>' if out_of_filter else ''}")
    brand = str(row["bandiera"] or row["impianto"] or "?").strip()
    lower_brand = brand.casefold()
    if "eni" in lower_brand or "agip" in lower_brand:
        badge, bg, fg = "eni", "#ffdf00", "#111111"
    elif "shell" in lower_brand:
        badge, bg, fg = "SH", "#ed1c24", "#ffffff"
    elif "q8" in lower_brand:
        badge, bg, fg = "Q8", "#e31b36", "#ffffff"
    elif "esso" in lower_brand:
        badge, bg, fg = "Esso", "#c8102e", "#ffffff"
    elif "api" in lower_brand or "ip" == lower_brand:
        badge, bg, fg = "IP", "#087b47", "#ffffff"
    elif "tamoil" in lower_brand:
        badge, bg, fg = "TAM", "#123b78", "#ffffff"
    elif "pompe bianche" in lower_brand:
        badge, bg, fg = "PB", "#4b5563", "#ffffff"
    else:
        badge = "".join(part[0] for part in re.findall(r"[A-Za-z0-9]+", brand)[:3]).upper() or "?"
        bg, fg = "#285f8f", "#ffffff"
    badge_html = (f'<div title="{supplier}" style="width:38px;height:38px;border-radius:50%;'
                  f'background:{bg};color:{fg};border:2px solid white;box-shadow:0 1px 5px #555;'
                  f'display:flex;align-items:center;justify-content:center;font:bold 11px Arial">{escape(badge)}</div>')
    supplier_icon = folium.DivIcon(html=badge_html, icon_size=(38, 38), icon_anchor=(19, 19), class_name="")
    marker_label = f"{supplier} · € {row['prezzo_num']:.3f}/L · {row['carburante']}"
    if out_of_filter:
        marker_label += " · fuori filtri"
    folium.Marker([row["lat"], row["lon"]], tooltip=marker_label,
                  popup=folium.Popup(popup, max_width=320), icon=supplier_icon).add_to(cluster)
folium.LayerControl().add_to(m)
st_folium(m, use_container_width=True, height=590, returned_objects=[])

st.subheader("⭐ Classifica evidenziata · Priverno, Sonnino e Terracina")
target_towns = {"PRIVERNO", "SONNINO", "TERRACINA"}
if featured.empty:
    st.info("Con i filtri attuali non ci sono risultati per Priverno, Sonnino o Terracina e il Tamoil di Sonnino Scalo non compare nei prezzi MIMIT disponibili.")
else:
    featured = featured.sort_values("prezzo_num")[["prezzo_num", "carburante", "comune", "bandiera", "impianto", "modalita", "indirizzo", "data_comunicazione", "fuori_filtri"]]
    featured = featured.rename(columns={"prezzo_num":"Prezzo €/L", "carburante":"Carburante", "comune":"Comune", "bandiera":"Fornitore", "impianto":"Impianto", "modalita":"Modalità", "indirizzo":"Indirizzo", "data_comunicazione":"Comunicazione", "fuori_filtri":"Filtro"})
    featured["Prezzo €/L"] = featured["Prezzo €/L"].map(lambda x: f"€ {x:.3f}")
    featured["Comunicazione"] = featured["Comunicazione"].dt.strftime("%d/%m/%Y").fillna("n.d.")
    with st.container(border=True):
        st.caption("Ordinata dal prezzo più conveniente al meno conveniente; rispetta carburante, periodo e ricerca comune selezionati.")
        st.dataframe(featured, use_container_width=True, hide_index=True)

st.subheader("Prezzi di tutti i distributori nei risultati filtrati")
table = view.sort_values("prezzo_num")[["prezzo_num", "carburante", "comune", "bandiera", "impianto", "indirizzo", "data_comunicazione"]].copy()
table = table.rename(columns={"prezzo_num":"Prezzo €/L", "carburante":"Carburante", "comune":"Comune", "bandiera":"Fornitore", "impianto":"Impianto", "indirizzo":"Indirizzo", "data_comunicazione":"Comunicazione"})
table["Prezzo €/L"] = table["Prezzo €/L"].map(lambda x: f"€ {x:.3f}")
table["Comunicazione"] = table["Comunicazione"].dt.strftime("%d/%m/%Y").fillna("n.d.")
st.dataframe(table, use_container_width=True, hide_index=True)
st.caption(f"Fonte: [MIMIT — Osservatorio Prezzi Carburanti]({SOURCE_URL}) · Licenza open data IODL 2.0 · Ultimo controllo eseguito all’apertura: {fetched_at.strftime('%d/%m/%Y %H:%M:%S')}")
