import geopandas as gpd
import pandas as pd
import folium
from PyPDF2 import PdfReader
import re
from datetime import datetime, timedelta
import os
import shutil # Per simulare il download
from flask import Flask, render_template, request, jsonify, send_from_directory
from shapely.geometry import Polygon # Per la demo di Ferrandina

app = Flask(__name__)

# --- Funzioni di Elaborazione (quasi le stesse del codice precedente) ---

def extract_bases_from_pdf(pdf_path):
    """
    Estrae le definizioni delle basi e i loro colori di criticità dal PDF del bollettino.
    """
    bases_criticity = {}
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text()

        legend_start_match = re.search(r"Legenda:\s*", text)
        if not legend_start_match:
            print("Avviso: Sezione 'Legenda:' non trovata nel PDF. Impossibile estrarre le basi.")
            return bases_criticity

        legend_start_index = legend_start_match.end()
        
        lines = text[legend_start_index:].split('\n')
        
        for line in lines:
            line = line.strip()
            match = re.match(r"Base\s+([A-Za-z0-9\s\/]+):\s*([A-Za-z]+)", line)
            if match:
                base_name = match.group(1).strip()
                color = match.group(2).strip().upper()
                bases_criticity[base_name] = color
            elif "Base Non Mappata / Nessun Rischio" in line:
                bases_criticity["Non Mappata"] = "VERDE"
                
            if not line and bases_criticity:
                break
            if len(bases_criticity) > 10:
                break
                
    except Exception as e:
        print(f"Errore durante l'estrazione delle basi dal PDF: {e}")
    
    return bases_criticity

def get_criticity_level_numeric(color):
    """
    Restituisce un valore numerico per il livello di criticità.
    """
    criticity_map = {
        "ROSSO": 4,
        "ARANCIONE": 3,
        "GIALLO": 2,
        "VERDE": 1,
        "NON MAPPATA": 1
    }
    return criticity_map.get(color.upper(), 0)

def assign_municipalities_criticity(gdf_municipalities, bases_criticity_data):
    """
    Assegna il livello di criticità a ciascun comune basandosi sulle basi di allerta
    e sulla regola della massima gravosità.

    *** QUESTA PARTE NECESSITA DELLA TUA LOGICA DI MAPPATURA REALE ***
    """
    gdf_municipalities['criticity_level_color'] = "VERDE"
    gdf_municipalities['criticity_level_numeric'] = get_criticity_level_numeric("VERDE")

    # --- INIZIO: placeholder per la mappatura COMUNE -> BASI ---
    # QUESTA DEVE ESSERE LA TUA LOGICA REALE!
    # Esempio:
    # 1. Caricare un GeoJSON delle "Basi" e fare un sjoin.
    # 2. Caricare un CSV di mappatura Comune-Base.
    # 3. Estrapolare dal PDF la mappatura (se presente).

    comune_to_bases_mapping_placeholder = {
        "Abriola": ["Base A2", "Base E1"],
        "Acerenza": ["Base C"],
        "Albano di Lucania": ["Base D"],
        "Anzi": ["Base A1", "Base B"],
        # Aggiungi altri comuni
        "Ferrandina": ["Base B", "Base E2"] # Esempio dal tuo input
    }
    # --- FINE: placeholder ---

    # Aggiungi Ferrandina al GeoDataFrame se non esiste per la demo
    if not any(gdf_municipalities['name'] == 'Ferrandina'):
        ferrandina_coords = [[16.0, 40.5], [16.1, 40.5], [16.1, 40.6], [16.0, 40.6], [16.0, 40.5]]
        ferrandina_properties = {
            "name": "Ferrandina", "minint_finloc": "", "op_id": "", "minint_elettorale": "",
            "prov_name": "Matera", "prov_istat_code": "077", "prov_acr": "MT",
            "reg_name": "Basilicata", "reg_istat_code": "17", "opdm_id": "",
            "com_catasto_code": "D546", "com_istat_code": "077010", "com_istat_code_num": 77010
        }
        ferrandina_gdf = gpd.GeoDataFrame([{"geometry": Polygon(ferrandina_coords), "properties": ferrandina_properties}], crs=gdf_municipalities.crs)
        gdf_municipalities = pd.concat([gdf_municipalities, ferrandina_gdf], ignore_index=True)


    for index, row in gdf_municipalities.iterrows():
        comune_name = row['name']
        applicable_bases = comune_to_bases_mapping_placeholder.get(comune_name, [])

        max_criticity_numeric = get_criticity_level_numeric("VERDE")
        final_criticity_color = "VERDE"

        for base_name in applicable_bases:
            base_color = bases_criticity_data.get(base_name, "VERDE")
            current_criticity_numeric = get_criticity_level_numeric(base_color)

            if current_criticity_numeric > max_criticity_numeric:
                max_criticity_numeric = current_criticity_numeric
                final_criticity_color = base_color

        gdf_municipalities.at[index, 'criticity_level_color'] = final_criticity_color
        gdf_municipalities.at[index, 'criticity_level_numeric'] = max_criticity_numeric

    return gdf_municipalities

def create_styled_map(gdf, title, output_dir, file_prefix, center_coords=[40.5, 16.0], zoom_start=8):
    """
    Crea mappe Folium per ogni livello di rischio e le salva.
    Restituisce un elenco dei percorsi dei file generati.
    """
    color_map = {
        "ROSSO": "darkred",
        "ARANCIONE": "orange",
        "GIALLO": "gold",
        "VERDE": "green",
        "NON MAPPATA": "lightgray"
    }
    
    unique_risks = gdf['criticity_level_color'].unique()
    generated_map_files = []

    for risk_color in sorted(unique_risks, key=lambda x: get_criticity_level_numeric(x), reverse=True):
        gdf_filtered = gdf[gdf['criticity_level_color'] == risk_color]
        
        if gdf_filtered.empty:
            continue

        m = folium.Map(location=center_coords, zoom_start=zoom_start, control_scale=True)

        folium.GeoJson(
            gdf_filtered,
            name=f'{risk_color} Municipalities',
            style_function=lambda feature: {
                'fillColor': color_map.get(feature['properties']['criticity_level_color'], 'lightgray'),
                'color': 'black',
                'weight': 0.5,
                'fillOpacity': 0.7
            },
            tooltip=folium.features.GeoJsonTooltip(fields=['name', 'criticity_level_color'],
                                                   aliases=['Comune:', 'Criticità:'],
                                                   localize=True)
        ).add_to(m)

        folium.TileLayer('OpenStreetMap').add_to(m)
        folium.LayerControl().add_to(m)

        map_filename = f"{file_prefix}_{risk_color.lower()}.html"
        full_path = os.path.join(output_dir, map_filename)
        m.save(full_path)
        generated_map_files.append(map_filename)
        print(f"Mappa per il rischio '{risk_color}' salvata in: {full_path}")
    
    return generated_map_files

# --- Configurazione Flask ---

STATIC_MAPS_DIR = os.path.join(app.root_path, 'static', 'maps')
# Assicurati che la directory esista
os.makedirs(STATIC_MAPS_DIR, exist_ok=True)

GEOJSON_MUNICIPALITIES_PATH = 'limits_R_17_municipalities.geojson'
# Questo è il file PDF che "simuliamo" di scaricare.
# In un ambiente reale, questo sarebbe l'URL o il percorso di download.
SIMULATED_PDF_PATH = 'bollettino_criticità_Idrogeologico_2025-05-28T11-24-47.pdf'


@app.route('/')
def index():
    """
    Pagina principale del portale.
    """
    # Ottieni i nomi dei file delle mappe già generati per visualizzarli subito
    # (o al refresh della pagina)
    generated_maps = []
    if os.path.exists(STATIC_MAPS_DIR):
        for f in os.listdir(STATIC_MAPS_DIR):
            if f.endswith('.html'):
                generated_maps.append(f)
    return render_template
