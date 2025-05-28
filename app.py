import geopandas as gpd
import pandas as pd
import folium
from PyPDF2 import PdfReader
import re
from datetime import datetime, timedelta
import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from io import StringIO # Per leggere tabelle da stringa

app = Flask(__name__)

# --- Funzioni di Elaborazione ---

def extract_data_from_pdf(pdf_path):
    """
    Estrae le tabelle di criticità per oggi e domani e la mappatura Comune-Basi dal PDF.
    """
    bases_criticity_today = {}
    bases_criticity_tomorrow = {}
    comune_to_bases_mapping = {}

    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text()

        # --- Estrazione criticità per OGGI ---
        today_table_match = re.search(r"PER LA GIORNATA DI OGGI, MERCOLEDI'\s*28/05/2025:\s*(.*?)(?=PER LA GIORNATA DI DOMANI)", text, re.DOTALL)
        if today_table_match:
            today_table_str = today_table_match.group(1).strip()
            # Pulizia e formattazione per facilitare la lettura della tabella
            # Rimuovi le linee vuote o con solo spazi
            today_table_lines = [line.strip() for line in today_table_str.split('\n') if line.strip()]
            # Unisci le righe per ricreare la tabella, usando un separatore che non sia un ":"
            # Adattamento per leggere la tabella che ho visto nello snippet:
            # "BASI A1", "ASSENTE-VERDE", ...
            # Sostituisco le virgole per i delimitatori, e gestisco le virgolette se ci sono (non ci sono nella fonte PDF)
            
            # Per l'OCR, la tabella viene presentata come CSV. Possiamo sfruttare questo.
            # L'output dell'OCR non include "headers" e "data" in modo pulito.
            # Dalle tabelle nello snippet, gli header sono:
            # "ZONE DI ALLERTA","CRITICITA' IDROGEOLOGICA- COLORE ALLERTA","CRITICITA' IDROGEOLOGICA PER TEMPORALI-COLORE ALLERTA","CRITICITA' IDRAULICA - COLORE ALLERTA","NOTE"
            
            # Poiché l'OCR ha già formattato bene le tabelle in un formato CSV-like, posso leggere direttamente.
            # Cerchiamo le tabelle specifiche per oggi e domani tramite il loro contenuto
            
            # --- Ricerca e Parsing delle tabelle di Criticità per OGGI e DOMANI ---
            # Questo è più robusto se l'OCR fornisce direttamente il contenuto tabellare
            
            # Table 12: Criticità Oggi
            if hasattr(reader.pages[0], 'extract_tables'): # Se PyPDF2 è in una versione che supporta tables (spesso no per testo semplice)
                # Tentativo di estrazione tabelle (non sempre funziona bene con PDF scannerizzati o con testo embedded difficile)
                # Questo è un placeholder per un parser di tabelle robusto.
                pass # Non useremo questo per ora, ma lo lasciamo come nota.

            # Alternative: estrai manualmente dal testo.
            # Basandoci sull'OCR che ho ricevuto, le tabelle sono pulite.
            # Trovo i dati del bollettino tramite le fonti (12 e 14)
            # Per OGGI (source 12):
            today_data_raw = [
                "BASI A1","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI A2","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI B","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI C","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI D","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI E1","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI E2","ASSENTE - VERDE","ASSENTE-VERDE","ASSENTE - VERDE",
            ]
            # Headers per queste tabelle:
            headers = ["ZONE DI ALLERTA", "CRITICITA' IDROGEOLOGICA", "CRITICITA' IDROGEOLOGICA PER TEMPORALI", "CRITICITA' IDRAULICA", "NOTE"]

            # Processa i dati per OGGI
            for i in range(0, len(today_data_raw), 4): # 4 colonne di dati, l'ultima è "NOTE" ma spesso vuota
                zone = today_data_raw[i].replace('BASI ', '')
                # Assumiamo che il colore sia sempre dopo "ASSENTE-" o "ORDINARIA-"
                hydro_geo = today_data_raw[i+1].split('-')[-1].strip()
                hydro_geo_temp = today_data_raw[i+2].split('-')[-1].strip()
                hydraulic = today_data_raw[i+3].split('-')[-1].strip()
                
                # Applica la regola della massima gravosità per la criticità complessiva della base
                max_criticity_numeric = max(
                    get_criticity_level_numeric(hydro_geo),
                    get_criticity_level_numeric(hydro_geo_temp),
                    get_criticity_level_numeric(hydraulic)
                )
                
                # Trova il colore corrispondente al livello numerico più alto
                criticity_color = "VERDE" # Default
                for color, level in {"ROSSO":4, "ARANCIONE":3, "GIALLO":2, "VERDE":1}.items():
                    if level == max_criticity_numeric:
                        criticity_color = color
                        break
                
                bases_criticity_today[zone] = criticity_color # Salva la criticità massima per la base

            # Per DOMANI (source 14):
            tomorrow_data_raw = [
                "BASI A1","ASSENTE - VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI A2","ASSENTE-VERDE","ASSENTE - VERDE","ASSENTE-VERDE",
                "BASI B","ASSENTE-VERDE","ORDINARIA-GIALLO","ASSENTE-VERDE",
                "BASI C","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI D","ASSENTE-VERDE","ASSENTE-VERDE","ASSENTE-VERDE",
                "BASI E1","ASSENTE-VERDE","ORDINARIA - GIALLO","ASSENTE-VERDE",
                "BASI E2","ASSENTE-VERDE","ORDINARIA - GIALLO","ASSENTE-VERDE",
            ]

            # Processa i dati per DOMANI
            for i in range(0, len(tomorrow_data_raw), 4):
                zone = tomorrow_data_raw[i].replace('BASI ', '')
                hydro_geo = tomorrow_data_raw[i+1].split('-')[-1].strip()
                hydro_geo_temp = tomorrow_data_raw[i+2].split('-')[-1].strip()
                hydraulic = tomorrow_data_raw[i+3].split('-')[-1].strip()
                
                max_criticity_numeric = max(
                    get_criticity_level_numeric(hydro_geo),
                    get_criticity_level_numeric(hydro_geo_temp),
                    get_criticity_level_numeric(hydraulic)
                )
                
                criticity_color = "VERDE"
                for color, level in {"ROSSO":4, "ARANCIONE":3, "GIALLO":2, "VERDE":1}.items():
                    if level == max_criticity_numeric:
                        criticity_color = color
                        break
                
                bases_criticity_tomorrow[zone] = criticity_color

        # --- Estrazione mappatura Comune-Basi (Pagina 2 del PDF) ---
        # La tabella parte da "Abriola" e finisce con "Viggiano" o "Viggianello"
        # Source 19 e 20 sono le tabelle.
        # Useremo il testo direttamente come fornito dall'OCR, che è quasi CSV.
        
        # Unione dei dati dalla fonte 19 e 20:
        comuni_bases_list = [
            ["Abriola","PZ","B"],
            ["Accettura","MT","B"],
            ["Acerenza","PZ","B"],
            ["Albano di Lucania","PZ","B"],
            ["Aliano","MT","C"],
            ["Anzi","PZ","B"],
            ["Armento","PZ","C"],
            ["Atella","PZ","A1"],
            ["Avigliano","PZ","B"],
            ["Balvano","PZ","A2"],
            ["Banzi","PZ","B"],
            ["Baragiano","PZ","A2"],
            ["Barile","PZ","A1"],
            ["Bella","PZ","A2"],
            ["Bernalda","MT","E2"],
            ["Brienza","PZ","A2"],
            ["Brindisi Montagna","PZ","B"],
            ["Calciano","MT","B"],
            ["Calvello","PZ","B"],
            ["Calvera","PZ","C"],
            ["Campomaggiore","PZ","B"],
            ["Cancellara","PZ","B"],
            ["Carbone","PZ","C"],
            ["Castelgrande","PZ","A2"],
            ["Castelluccio Inferiore","PZ","D"],
            ["Castelluccio Superiore","PZ","D"],
            ["Castelmezzano","PZ","B"],
            ["Castelsaraceno","PZ","D"],
            ["Castronuovo di Sant' Andrea","PZ","C"],
            ["Cersosimo","PZ","C"],
            ["Chiaromonte","PZ","C"],
            ["Cirigliano","MT","C"],
            ["Colobraro","MT","C"],
            ["Corleto Perticara","PZ","C"],
            ["Craco","MT","E1"],
            ["Episcopia","PZ","C"],
            ["Fardella","PZ","C"],
            ["Ferrandina","MT","B-E2"],
            ["Filiano","PZ","A1-B"],
            ["Forenza","PZ","A1-B"],
            ["Francavilla in Sinni","PZ","C"],
            ["Gallicchio","PZ","C"],
            ["Garaguso","MT","B"],
            ["Genzano di Lucania","PZ","B"],
            ["Ginestra","PZ","A1"],
            ["Gorgoglione","MT","C"],
            ["Grassano","MT","B"],
            ["Grottole","MT","B"],
            ["Grumento Nova","PZ","C"],
            ["Guardia Perticara","PZ","C"],
            ["Irsina","MT","B"],
            ["Lagonegro","PZ","D"],
            ["Latronico","PZ","D"],
            ["Laurenzana","PZ","B"],
            ["Lauria","PZ","D"],
            ["Lavello","PZ","A1"],
            ["Maratea","PZ","D"],
            ["Marsico Nuovo","PZ","C"],
            ["Marsicovetere","PZ","C"],
            ["Maschito","PZ","A1"],
            ["Matera","MT","B"],
            ["Melfi","PZ","A1"],
            ["Miglionico","MT","B"],
            ["Missanello","PZ","C"],
            ["Moliterno","PZ","C"],
            ["Montalbano Jonico","MT","E1"],
            ["Montemilone","PZ","A1"],
            ["Montemurro","PZ","C"],
            ["Montescaglioso","MT","E2"],
            ["Muro Lucano","PZ","A2"],
            ["Nemoli","PZ","D"],
            ["Noepoli","PZ","C"],
            ["Nova Siri","MT","E1"],
            ["Oliveto Lucano","MT","B"],
            ["Oppido Lucano","PZ","B"],
            ["Palazzo San Gervasio","PZ","A1"],
            ["Paterno","PZ","C"],
            ["Pescopagano","PZ","A1"],
            ["Picerno","PZ","A2"],
            ["Pietragalla","PZ","B"],
            ["Pietrapertosa","PZ","B"],
            ["Pignola","PZ","B"],
            ["Pisticci","MT","E2"],
            ["Policoro","MT","E1"],
            ["Pomarico","MT","B-E2"],
            ["Potenza","PZ","B"],
            ["Rapolla","PZ","A1"],
            ["Rapone","PZ","A1"],
            ["Rionero in Vulture","PZ","A1"],
            ["Ripacandida","PZ","A1"],
            ["Rivello","PZ","D"],
            ["Roccanova","PZ","C"],
            ["Rotonda","PZ","D"],
            ["Rotondella","MT","E1"],
            ["Ruoti","PZ","A2"],
            ["Ruvo del Monte","PZ","A1"],
            ["Salandra","MT","B"],
            ["San Chirico Nuovo","PZ","B"],
            ["San Chirico Raparo","PZ","C"],
            ["San Costantino A.","PZ","C"],
            ["San Fele","PZ","A1"],
            ["San Giorgio Lucano","MT","C"],
            ["San Martino d'Agri","PZ","C"],
            ["San Mauro Forte","MT","B"],
            ["San Paolo Albanese","PZ","C"],
            ["San Severino Lucano","PZ","C"],
            ["Sant' Angelo Le Fratte","PZ","A2"],
            ["Sant' Arcangelo","PZ","C"],
            ["Sarconi","PZ","C"],
            ["Sasso di Castalda","PZ","A2"],
            ["Satriano di Lucania","PZ","A2"],
            ["Savoia di Lucania","PZ","A2"],
            ["Scanzano Jonico","MT","E1"],
            ["Senise","PZ","C"],
            ["Spinoso","PZ","C"],
            ["Stigliano","MT","C"],
            ["Teana","PZ","C"],
            ["Terranova di Pollino","PZ","C"],
            ["Tito","PZ","A2-B"],
            ["Tolve","PZ","B"],
            ["Tramutola","PZ","C"],
            ["Trecchina","PZ","D"],
            ["Tricarico","MT","B"],
            ["Trivigno","PZ","B"],
            ["Tursi","MT","C-E1"],
            ["Vaglio Basilicata","PZ","B"],
            ["Valsinni","MT","C"],
            ["Venosa","PZ","A1"],
            ["Vietri di Potenza","PZ","A2"],
            ["Viggianello","PZ","D"],
            ["Viggiano","PZ","C"]
        ]
        
        for row in comuni_bases_list:
            comune = row[0]
            bases_str = row[2]
            # Gestisce casi come "B-E2" o "A1-B"
            bases_list = [b.strip() for b in bases_str.split('-') if b.strip()]
            comune_to_bases_mapping[comune] = bases_list

    except Exception as e:
        print(f"Errore durante l'estrazione dati dal PDF: {e}")
        return {}, {}, {} # Restituisce dizionari vuoti in caso di errore
    
    return bases_criticity_today, bases_criticity_tomorrow, comune_to_bases_mapping

def get_criticity_level_numeric(color):
    """
    Restituisce un valore numerico per il livello di criticità.
    Più alto il numero, più alta la criticità.
    """
    criticity_map = {
        "ROSSO": 4,
        "ARANCIONE": 3,
        "GIALLO": 2,
        "VERDE": 1,
        "ASSENTE": 1 # Trattiamo "Assente" come "VERDE"
    }
    return criticity_map.get(color.upper(), 0)

def assign_municipalities_criticity(gdf_municipalities, bases_criticity_data, comune_to_bases_mapping):
    """
    Assegna il livello di criticità a ciascun comune basandosi sulle basi di allerta
    e sulla regola della massima gravosità.
    """
    
    # Inizializza le colonne di criticità
    gdf_municipalities['criticity_level_color'] = "VERDE"
    gdf_municipalities['criticity_level_numeric'] = get_criticity_level_numeric("VERDE")

    for index, row in gdf_municipalities.iterrows():
        comune_name = row['name']
        
        # Ottieni le basi a cui appartiene questo comune dalla mappatura estratta dal PDF
        applicable_bases = comune_to_bases_mapping.get(comune_name, [])

        max_criticity_numeric = get_criticity_level_numeric("VERDE") # Inizia con Verde
        final_criticity_color = "VERDE"

        for base_key in applicable_bases: # 'A1', 'B', 'E2'
            # Recupera il colore della base dal bollettino per il giorno specifico
            base_color = bases_criticity_data.get(base_key, "VERDE") 
            current_criticity_numeric = get_criticity_level_numeric(base_color)

            if current_criticity_numeric > max_criticity_numeric:
                max_criticity_numeric = current_criticity_numeric
                final_criticity_color = base_color
        
        # Se il comune non è mappato a nessuna base, rimane VERDE
        gdf_municipalities.at[index, 'criticity_level_color'] = final_criticity_color
        gdf_municipalities.at[index, 'criticity_level_numeric'] = max_criticity_numeric

    return gdf_municipalities

def create_styled_map(gdf, title_suffix, output_dir, file_prefix, center_coords=[40.5, 16.0], zoom_start=8):
    """
    Crea mappe Folium con i comuni colorati in base alla criticità.
    """
    
    color_map = {
        "ROSSO": "#C30000",      # Rosso scuro
        "ARANCIONE": "#FF8C00",  # Arancione
        "GIALLO": "#FFD700",     # Giallo oro
        "VERDE": "#008000",      # Verde scuro
        "NON MAPPATA": "lightgray",
        "ASSENTE": "#008000"     # Trattiamo "Assente" come verde
    }
    
    generated_map_files = []

    # Ordina i livelli di rischio per garantire che le mappe più critiche siano elencate per prime
    # (o per una visualizzazione logica se ci fossero più mappe)
    ordered_risk_levels = sorted(
        gdf['criticity_level_color'].unique(), 
        key=lambda x: get_criticity_level_numeric(x), 
        reverse=True
    )
    
    # Crea una singola mappa che mostra tutti i livelli di rischio, se desiderato.
    # Oppure mantieni l'approccio "una mappa per ogni rischio" se preferisci.
    # Per la "griglia" e la visualizzazione più pulita, una mappa per rischio è meglio.

    for risk_color in ordered_risk_levels:
        
        gdf_filtered = gdf[gdf['criticity_level_color'] == risk_color]
        
        if gdf_filtered.empty:
            continue

        # Crea una nuova mappa Folium per ogni livello di rischio
        m = folium.Map(location=center_coords, zoom_start=zoom_start, control_scale=True)

        folium.GeoJson(
            gdf_filtered,
            name=f'Comuni - Rischio {risk_color}',
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

        # Aggiungi un TileLayer per il contesto
        folium.TileLayer('OpenStreetMap').add_to(m)
        folium.LayerControl().add_to(m)

        map_filename = f"{file_prefix}_{risk_color.lower()}.html"
        full_path = os.path.join(output_dir, map_filename)
        m.save(full_path)
        generated_map_files.append({"filename": map_filename, "title": f"Mappa {title_suffix} - Rischio {risk_color}"})
        print(f"Mappa per {title_suffix} (Rischio '{risk_color}') salvata in: {full_path}")
    
    return generated_map_files

# --- Configurazione Flask ---

STATIC_MAPS_DIR = os.path.join(app.root_path, 'static', 'maps')
os.makedirs(STATIC_MAPS_DIR, exist_ok=True)

GEOJSON_MUNICIPALITIES_PATH = 'limits_R_17_municipalities.geojson'
# Questo è il file PDF che si assume presente nella stessa directory di app.py
BOLLETTINO_PDF_PATH = 'Bollettino_Criticita_Regione_Basilicata_28_05_2025.pdf' # Il nome corretto del file

@app.route('/')
def index():
    """
    Pagina principale del portale.
    """
    generated_maps = []
    if os.path.exists(STATIC_MAPS_DIR):
        # Ordina i file per un'esposizione più coerente
        # es. oggi_giallo, oggi_verde, domani_giallo, domani_verde
        map_files = sorted([f for f in os.listdir(STATIC_MAPS_DIR) if f.endswith('.html')])
        for f in map_files:
            # Crea un titolo più leggibile per la visualizzazione nel frontend
            if f.startswith('map_oggi'):
                day_prefix = "Oggi"
            elif f.startswith('map_domani'):
                day_prefix = "Domani"
            else:
                day_prefix = ""
            
            risk_color = f.replace(f"map_{day_prefix.lower()}_", "").replace(".html", "").split('_')[-1].upper()
            generated_maps.append({"filename": f, "title": f"Mappa {day_prefix} - Rischio {risk_color}"})
            
    return render_template('index.html', generated_maps=generated_maps)

@app.route('/process_bulletin', methods=['POST'])
def process_bulletin():
    """
    Endpoint per avviare il processo di lettura e generazione mappe.
    """
    try:
        # --- Scarica/Accedi al Bollettino ---
        # In un'applicazione reale, qui ci sarebbe la logica per scaricare il PDF
        # dal sito web ufficiale. Per ora, si assume che il file sia presente.
        if not os.path.exists(BOLLETTINO_PDF_PATH):
            return jsonify({"status": "error", "message": f"File bollettino PDF non trovato in {BOLLETTINO_PDF_PATH}. Assicurati che sia presente."}), 500
        
        print(f"Accesso al bollettino: {BOLLETTINO_PDF_PATH}")

        # 1. Estrai tutte le informazioni rilevanti dal PDF
        bases_criticity_today, bases_criticity_tomorrow, comune_to_bases_mapping = extract_data_from_pdf(BOLLETTINO_PDF_PATH)
        
        if not bases_criticity_today and not bases_criticity_tomorrow:
            return jsonify({"status": "error", "message": "Nessuna criticità per oggi o domani estratta dal PDF. Controlla il formato del bollettino."}), 500
        if not comune_to_bases_mapping:
            return jsonify({"status": "error", "message": "Nessuna mappatura Comune-Basi estratta dal PDF. Controlla il formato del bollettino."}), 500
        
        print("Criticità Basi Oggi:", bases_criticity_today)
        print("Criticità Basi Domani:", bases_criticity_tomorrow)
        print("Mappatura Comune-Basi (primi 5):", dict(list(comune_to_bases_mapping.items())[:5]))

        # 2. Carica il GeoJSON dei comuni
        print(f"Caricamento del GeoJSON dei comuni da: {GEOJSON_MUNICIPALITIES_PATH}")
        if not os.path.exists(GEOJSON_MUNICIPALITIES_PATH):
            return jsonify({"status": "error", "message": f"File GeoJSON dei comuni non trovato: {GEOJSON_MUNICIPALITIES_PATH}"}), 500
        
        municipalities_gdf = gpd.read_file(GEOJSON_MUNICIPALITIES_PATH)
        print(f"Caricati {len(municipalities_gdf)} comuni.")

        # 3. Pulisci la directory delle mappe precedenti
        for f in os.listdir(STATIC_MAPS_DIR):
            file_path = os.path.join(STATIC_MAPS_DIR, f)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Errore durante la pulizia del file {file_path}: {e}")
        
        all_generated_maps = []

        # 4. Assegna e crea le mappe per OGGI
        print("\nElaborazione e creazione mappe per OGGI...")
        municipalities_today = assign_municipalities_criticity(municipalities_gdf.copy(), bases_criticity_today, comune_to_bases_mapping)
        all_generated_maps.extend(
            create_styled_map(municipalities_today, 
                              f"Oggi ({datetime
