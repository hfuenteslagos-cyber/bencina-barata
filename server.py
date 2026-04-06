#!/usr/bin/env python3
"""
Bencina Barata - Servidor backend
Obtiene precios REALES desde preciobencina.cl + servidor estatico
"""

import http.server
import json
import re
import urllib.request
import urllib.parse
import urllib.error
import os
import time
import html as html_module

PORT = int(os.environ.get("PORT", 8080))
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_estaciones.json")
CACHE_TTL = 3600  # 1 hora - los precios se actualizan semanalmente (jueves)

SCRAPE_URL = "https://preciobencina.cl/bencineras-en-region-de-antofagasta.php"

# ── Scraping preciobencina.cl ────────────────────────────────────────────────

def fetch_precios_reales():
    """Scrapea preciobencina.cl para obtener precios reales de la Region de Antofagasta."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-CL,es;q=0.9",
    }

    try:
        req = urllib.request.Request(SCRAPE_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            page_html = resp.read().decode("utf-8", errors="replace")

        if "L.marker" not in page_html:
            print("  [WARN] Pagina no contiene datos de marcadores")
            return None

        estaciones = parse_markers(page_html)
        if estaciones:
            print(f"  [OK] {len(estaciones)} estaciones scrapeadas de preciobencina.cl")
            return estaciones

    except Exception as e:
        print(f"  [WARN] Error scrapeando preciobencina.cl: {e}")

    return None


def parse_markers(page_html):
    """Parsea los L.marker() del HTML de preciobencina.cl"""
    estaciones = []

    # Patron para encontrar cada L.marker con su popup
    # L.marker([lat, lng], {icon: ...}).addTo(map).bindPopup('...')
    marker_pattern = re.compile(
        r"L\.marker\(\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\].*?\.bindPopup\('(.*?)'\)",
        re.DOTALL
    )

    for i, match in enumerate(marker_pattern.finditer(page_html)):
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
            popup_html = match.group(3)

            # Decodificar escapes de JS
            popup_html = popup_html.replace("\\'", "'").replace("\\n", "\n")

            # Extraer marca/nombre
            brand_match = re.search(r"<h3[^>]*>(.*?)</h3>", popup_html, re.DOTALL)
            brand = clean_html(brand_match.group(1)) if brand_match else "Desconocida"

            # Extraer direccion
            addr_match = re.search(r"<h4[^>]*>.*?</i>\s*(.*?)</h4>", popup_html, re.DOTALL)
            direccion = clean_html(addr_match.group(1)).strip() if addr_match else ""

            # Extraer comuna de la direccion (despues de la ultima coma)
            comuna = ""
            if "," in direccion:
                parts = direccion.rsplit(",", 1)
                candidate = parts[-1].strip()
                # Verificar que parece una comuna real (no un numero o parte de direccion)
                known_comunas = ["Antofagasta", "Tocopilla", "Calama", "Mejillones",
                                 "Taltal", "San Pedro de Atacama", "Sierra Gorda", "Maria Elena"]
                if any(c.lower() in candidate.lower() for c in known_comunas):
                    comuna = candidate
                    direccion = parts[0].strip()
                else:
                    # La "comuna" detectada no es real, usar coordenadas
                    comuna = guess_comuna(lat, lng)
            else:
                comuna = guess_comuna(lat, lng)

            # Extraer precios
            precios = {}
            # Bencina 93
            p93 = re.search(r"(?:Bencina|Gasolina)\s*93.*?\$\s*([\d.,]+)", popup_html)
            if p93:
                precios["Gasolina 93"] = parse_price(p93.group(1))
            # Bencina 95
            p95 = re.search(r"(?:Bencina|Gasolina)\s*95.*?\$\s*([\d.,]+)", popup_html)
            if p95:
                precios["Gasolina 95"] = parse_price(p95.group(1))
            # Bencina 97
            p97 = re.search(r"(?:Bencina|Gasolina)\s*97.*?\$\s*([\d.,]+)", popup_html)
            if p97:
                precios["Gasolina 97"] = parse_price(p97.group(1))
            # Diesel
            pd = re.search(r"[Dd]iesel.*?\$\s*([\d.,]+)", popup_html)
            if pd:
                precios["Diesel"] = parse_price(pd.group(1))
            # Kerosene
            pk = re.search(r"[Kk]erosene.*?\$\s*([\d.,]+)", popup_html)
            if pk:
                precios["Kerosene"] = parse_price(pk.group(1))

            # Extraer ID de estacion
            id_match = re.search(r"detalles-bencinera\.php\?i=(\w+)", popup_html)
            station_id = id_match.group(1) if id_match else f"s{i+1}"

            # Determinar distribuidor limpio
            distribuidor = normalize_brand(brand)

            if precios and lat != 0 and lng != 0:
                estaciones.append({
                    "id": station_id,
                    "nombre": f"{distribuidor} - {direccion}" if direccion else distribuidor,
                    "direccion": direccion,
                    "comuna": comuna,
                    "distribuidor": distribuidor,
                    "lat": lat,
                    "lng": lng,
                    "precios": precios,
                })

        except Exception as e:
            continue

    return estaciones if estaciones else None


def clean_html(text):
    """Limpia tags HTML y decodifica entidades."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    return text.strip()


def parse_price(price_str):
    """Convierte string de precio a int: '1.236' -> 1236, '1,236' -> 1236."""
    cleaned = price_str.replace(".", "").replace(",", "").strip()
    # Si el numero es muy chico (ej: 1236 sin punto), retornar directo
    try:
        val = int(cleaned)
        return val if val > 100 else 0
    except ValueError:
        return 0


def normalize_brand(raw_brand):
    """Normaliza nombre de marca."""
    b = raw_brand.upper().strip()
    if "COPEC" in b:
        return "Copec"
    if "SHELL" in b:
        return "Shell"
    if "PETROBRAS" in b or "ENEX" in b:
        return "Petrobras"
    if "TERPEL" in b:
        return "Terpel"
    if "ARAUCO" in b:
        return "Arauco"
    if "AUTOGASCO" in b:
        return "Autogasco"
    return raw_brand.strip()


def guess_comuna(lat, lng):
    """Estima la comuna basado en coordenadas."""
    # Rangos aproximados para comunas principales
    if -22.15 < lat < -22.02 and -70.25 < lng < -70.15:
        return "Tocopilla"
    if -23.15 < lat < -23.05 and -70.50 < lng < -70.40:
        return "Mejillones"
    if -23.80 < lat < -23.55 and -70.45 < lng < -70.30:
        return "Antofagasta"
    if -22.50 < lat < -22.40 and -69.00 < lng < -68.85:
        return "Calama"
    if -25.45 < lat < -25.35 and -70.55 < lng < -70.40:
        return "Taltal"
    if -22.95 < lat < -22.85 and -68.25 < lng < -68.15:
        return "San Pedro de Atacama"
    if -22.95 < lat < -22.85 and -69.40 < lng < -69.25:
        return "Sierra Gorda"
    if -22.40 < lat < -22.30 and -69.75 < lng < -69.60:
        return "Maria Elena"
    return "Antofagasta"


# ── Fallback data ────────────────────────────────────────────────────────────

def get_fallback_data():
    """Datos verificados como respaldo si el scraping falla.
    Fuentes: preciobencina.cl, bencinaenlinea.cl (CNE).
    IMPORTANTE: precios son referenciales, los reales vienen del scraping.
    """
    return [
        # TOCOPILLA (3 reales: 2 Copec + 1 Shell)
        {"id": "t1", "nombre": "Copec - Av. 11 de Septiembre", "direccion": "Av. 11 de Septiembre 000", "comuna": "Tocopilla", "distribuidor": "Copec", "lat": -22.0922, "lng": -70.1979, "precios": {"Gasolina 93": 1289, "Gasolina 95": 1359, "Gasolina 97": 1429, "Diesel": 1049}},
        {"id": "t2", "nombre": "Copec - Tte. Merino", "direccion": "Avda. Teniente Merino 3303", "comuna": "Tocopilla", "distribuidor": "Copec", "lat": -22.0850, "lng": -70.1935, "precios": {"Gasolina 93": 1289, "Gasolina 95": 1359, "Gasolina 97": 1429, "Diesel": 1049}},
        {"id": "t3", "nombre": "Shell - Costanera", "direccion": "Avda. Costanera s/n", "comuna": "Tocopilla", "distribuidor": "Shell", "lat": -22.0940, "lng": -70.1995, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Gasolina 97": 1439, "Diesel": 1059}},
        # MEJILLONES (2 reales: Copec)
        {"id": "m1", "nombre": "Copec - San Martin", "direccion": "San Martin 525", "comuna": "Mejillones", "distribuidor": "Copec", "lat": -23.0983, "lng": -70.4517, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Gasolina 97": 1425, "Diesel": 1045}},
        {"id": "m2", "nombre": "Copec - Av. Fertilizantes", "direccion": "Av. Fertilizantes esq. Riquelme", "comuna": "Mejillones", "distribuidor": "Copec", "lat": -23.1010, "lng": -70.4480, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Diesel": 1045}},
        # ANTOFAGASTA (muestra de principales)
        {"id": "a1", "nombre": "Copec - Av. Rendic", "direccion": "Av. Antonio Rendic 3855", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6280, "lng": -70.3920, "precios": {"Gasolina 93": 1236, "Gasolina 95": 1271, "Gasolina 97": 1301, "Diesel": 1047}},
        {"id": "a2", "nombre": "Shell - PAC 10615", "direccion": "Av. Pedro Aguirre Cerda 10615", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.5780, "lng": -70.3790, "precios": {"Gasolina 93": 1235, "Gasolina 95": 1270, "Gasolina 97": 1300, "Diesel": 1046}},
        {"id": "a3", "nombre": "Petrobras - Av. Grecia", "direccion": "Avda. Grecia 430", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6350, "lng": -70.3935, "precios": {"Gasolina 93": 1230, "Gasolina 95": 1265, "Gasolina 97": 1295, "Diesel": 1040}},
        # CALAMA
        {"id": "c1", "nombre": "Copec - Granaderos", "direccion": "Granaderos 3524", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4560, "lng": -68.9293, "precios": {"Gasolina 93": 1247, "Gasolina 95": 1280, "Gasolina 97": 1309, "Diesel": 1066}},
        {"id": "c2", "nombre": "Shell - Balmaceda", "direccion": "Balmaceda 4539", "comuna": "Calama", "distribuidor": "Shell", "lat": -22.4490, "lng": -68.9190, "precios": {"Gasolina 93": 1248, "Gasolina 95": 1281, "Gasolina 97": 1310, "Diesel": 1066}},
        # TALTAL
        {"id": "tt1", "nombre": "Copec - Francisco Bilbao", "direccion": "Francisco Bilbao 101", "comuna": "Taltal", "distribuidor": "Copec", "lat": -25.4053, "lng": -70.4828, "precios": {"Gasolina 93": 1261, "Gasolina 95": 1292, "Gasolina 97": 1325, "Diesel": 1065}},
        # SIERRA GORDA
        {"id": "sg1", "nombre": "Copec - Carmen Alto", "direccion": "Carmen Alto 1458", "comuna": "Sierra Gorda", "distribuidor": "Copec", "lat": -22.8933, "lng": -69.3236, "precios": {"Gasolina 93": 1335, "Gasolina 95": 1405, "Gasolina 97": 1475, "Diesel": 1095}},
        # SAN PEDRO DE ATACAMA
        {"id": "sp1", "nombre": "Copec - Ruta 27", "direccion": "Ruta 27 Interseccion B241", "comuna": "San Pedro de Atacama", "distribuidor": "Copec", "lat": -22.9087, "lng": -68.1997, "precios": {"Gasolina 93": 1349, "Gasolina 95": 1419, "Gasolina 97": 1489, "Diesel": 1109}},
    ]


# ── Cache y carga ────────────────────────────────────────────────────────────

def save_cache(estaciones, source):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "timestamp": time.time(),
                "source": source,
                "estaciones": estaciones,
            }, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [WARN] No se pudo guardar cache: {e}")


def load_estaciones():
    """Carga estaciones: cache valido → scraping real → fallback."""
    # 1. Intentar cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cached = json.load(f)
            age = time.time() - cached.get("timestamp", 0)
            if age < CACHE_TTL:
                src = cached.get("source", "cache")
                est = cached["estaciones"]
                mins = int((CACHE_TTL - age) / 60)
                print(f"  [OK] {len(est)} estaciones desde cache ({src}, expira en {mins}min)")
                return est, src
        except Exception:
            pass

    # 2. Scraping real de preciobencina.cl
    print("  [INFO] Scrapeando precios reales de preciobencina.cl...")
    estaciones = fetch_precios_reales()
    if estaciones and len(estaciones) >= 5:
        save_cache(estaciones, "preciobencina.cl")
        return estaciones, "preciobencina.cl"

    # 3. Fallback
    print("  [WARN] Usando datos de respaldo")
    estaciones = get_fallback_data()
    save_cache(estaciones, "fallback")
    return estaciones, "fallback"


# ── Servidor HTTP ────────────────────────────────────────────────────────────

ESTACIONES = []
DATA_SOURCE = "loading"
LAST_UPDATE = 0


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), **kwargs)

    def do_GET(self):
        global ESTACIONES, DATA_SOURCE, LAST_UPDATE
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/estaciones":
            self.send_json({
                "estaciones": ESTACIONES,
                "source": DATA_SOURCE,
                "count": len(ESTACIONES),
                "updated": LAST_UPDATE,
                "next_update": LAST_UPDATE + CACHE_TTL,
            })

        elif parsed.path == "/api/refresh":
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
            ESTACIONES, DATA_SOURCE = load_estaciones()
            LAST_UPDATE = time.time()
            self.send_json({
                "estaciones": ESTACIONES,
                "source": DATA_SOURCE,
                "count": len(ESTACIONES),
                "updated": LAST_UPDATE,
            })

        else:
            if parsed.path == "/":
                self.path = "/index.html"
            super().do_GET()

    def send_json(self, data):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)


def main():
    global ESTACIONES, DATA_SOURCE, LAST_UPDATE
    print("\n⛽ Bencina Barata - Region de Antofagasta")
    print("=" * 45)
    ESTACIONES, DATA_SOURCE = load_estaciones()
    LAST_UPDATE = time.time()
    print(f"\n🌐 Servidor: http://localhost:{PORT}")
    print(f"   Fuente: {DATA_SOURCE}")
    print(f"   Estaciones: {len(ESTACIONES)}")
    print(f"   Cache TTL: {CACHE_TTL//60} min")
    print(f"\n   Abre http://localhost:{PORT} en tu navegador\n")

    server = http.server.HTTPServer(("", PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Servidor detenido")
        server.server_close()


if __name__ == "__main__":
    main()
