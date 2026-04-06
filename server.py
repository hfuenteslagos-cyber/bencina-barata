#!/usr/bin/env python3
"""
Bencina Barata - Servidor backend
Proxy para API de CNE (bencinaenlinea.cl) + servidor estático
"""

import http.server
import json
import urllib.request
import urllib.parse
import urllib.error
import os
import time
import threading

PORT = int(os.environ.get("PORT", 8080))
CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache_estaciones.json")
CACHE_TTL = 3600  # 1 hora

# ── API CNE ──────────────────────────────────────────────────────────────────

CNE_API_URLS = [
    "https://api.cne.cl/v3/combustibles/vehicular/estaciones?regionId=2&formatoJson=true",
    "https://api.bencinaenlinea.cl/api/estaciones/region/2",
]


def fetch_estaciones_cne():
    """Intenta obtener estaciones desde la API de CNE."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BencinaBarata/1.0)",
        "Accept": "application/json",
    }
    for url in CNE_API_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data:
                    return data
        except Exception as e:
            print(f"  [WARN] API {url[:50]}... falló: {e}")
    return None


def normalize_estaciones(raw_data):
    """Normaliza datos de diferentes fuentes al formato interno."""
    estaciones = []
    items = raw_data if isinstance(raw_data, list) else raw_data.get("data", raw_data.get("estaciones", []))

    for item in items:
        try:
            est = {
                "id": item.get("id", item.get("id_estacion", "")),
                "nombre": item.get("nombre", item.get("nombre_estacion", item.get("razon_social", ""))),
                "direccion": item.get("direccion", item.get("direccion_calle", "")),
                "comuna": item.get("comuna", item.get("nombre_comuna", "")),
                "distribuidor": item.get("distribuidor", item.get("nombre_distribuidor", item.get("marca", ""))),
                "lat": float(item.get("latitud", item.get("lat", 0))),
                "lng": float(item.get("longitud", item.get("lng", item.get("lon", 0)))),
                "precios": {},
            }

            # Extraer precios según el formato
            if "precios" in item and isinstance(item["precios"], list):
                for p in item["precios"]:
                    tipo = p.get("tipo", p.get("nombre_combustible", ""))
                    precio = p.get("precio", p.get("valor", 0))
                    if tipo and precio:
                        est["precios"][tipo.strip()] = int(float(precio))
            else:
                # Formato plano con campos de precio directo
                for key_map in [
                    ("gasolina_93", "Gasolina 93"),
                    ("gasolina_95", "Gasolina 95"),
                    ("gasolina_97", "Gasolina 97"),
                    ("petroleo_diesel", "Diesel"),
                    ("kerosene", "Kerosene"),
                    ("precio_gasolina_93", "Gasolina 93"),
                    ("precio_gasolina_95", "Gasolina 95"),
                    ("precio_gasolina_97", "Gasolina 97"),
                    ("precio_petroleo_diesel", "Diesel"),
                    ("precio_kerosene", "Kerosene"),
                    ("glp_vehicular", "GLP"),
                ]:
                    val = item.get(key_map[0])
                    if val and float(val) > 0:
                        est["precios"][key_map[1]] = int(float(val))

            # Solo incluir si tiene coordenadas válidas en la región
            if est["lat"] != 0 and est["lng"] != 0 and est["precios"]:
                estaciones.append(est)

        except (ValueError, TypeError, KeyError) as e:
            continue

    return estaciones


def get_fallback_data():
    """Datos de respaldo con estaciones reales de la Región de Antofagasta."""
    return [
        {"id": "f1", "nombre": "Copec Tocopilla Centro", "direccion": "Av. Arturo Prat 1350", "comuna": "Tocopilla", "distribuidor": "Copec", "lat": -22.0936, "lng": -70.1961, "precios": {"Gasolina 93": 1289, "Gasolina 95": 1359, "Gasolina 97": 1429, "Diesel": 1049}},
        {"id": "f2", "nombre": "Shell Tocopilla", "direccion": "Av. 21 de Mayo 2100", "comuna": "Tocopilla", "distribuidor": "Shell", "lat": -22.0890, "lng": -70.1950, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Gasolina 97": 1439, "Diesel": 1059}},
        {"id": "f3", "nombre": "Petrobras Tocopilla", "direccion": "Ruta 1 Km 3", "comuna": "Tocopilla", "distribuidor": "ENEX", "lat": -22.0980, "lng": -70.1985, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Diesel": 1039}},
        {"id": "f4", "nombre": "Copec Antofagasta Centro", "direccion": "Av. Argentina 500", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6345, "lng": -70.3920, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "f5", "nombre": "Shell Antofagasta Norte", "direccion": "Av. Pedro Aguirre Cerda 8500", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.6010, "lng": -70.3880, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Gasolina 97": 1419, "Diesel": 1039}},
        {"id": "f6", "nombre": "Copec Antofagasta Sur", "direccion": "Av. Edmundo Pérez Zujovic 2800", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6750, "lng": -70.4050, "precios": {"Gasolina 93": 1265, "Gasolina 95": 1335, "Gasolina 97": 1405, "Diesel": 1025}},
        {"id": "f7", "nombre": "ENEX Antofagasta", "direccion": "Av. Angamos 700", "comuna": "Antofagasta", "distribuidor": "ENEX", "lat": -23.6520, "lng": -70.3960, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Diesel": 1019}},
        {"id": "f8", "nombre": "Terpel Antofagasta", "direccion": "Av. Iquique 1200", "comuna": "Antofagasta", "distribuidor": "Terpel", "lat": -23.6410, "lng": -70.3945, "precios": {"Gasolina 93": 1275, "Gasolina 95": 1345, "Gasolina 97": 1415, "Diesel": 1035}},
        {"id": "f9", "nombre": "Copec Calama", "direccion": "Av. Balmaceda 3500", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4540, "lng": -68.9310, "precios": {"Gasolina 93": 1309, "Gasolina 95": 1379, "Gasolina 97": 1449, "Diesel": 1069}},
        {"id": "f10", "nombre": "Shell Calama", "direccion": "Av. Granaderos 2000", "comuna": "Calama", "distribuidor": "Shell", "lat": -22.4600, "lng": -68.9250, "precios": {"Gasolina 93": 1319, "Gasolina 95": 1389, "Gasolina 97": 1459, "Diesel": 1079}},
        {"id": "f11", "nombre": "ENEX Calama Centro", "direccion": "Calle Ramírez 1800", "comuna": "Calama", "distribuidor": "ENEX", "lat": -22.4570, "lng": -68.9280, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Diesel": 1059}},
        {"id": "f12", "nombre": "Copec Mejillones", "direccion": "Av. San Martín 500", "comuna": "Mejillones", "distribuidor": "Copec", "lat": -23.0990, "lng": -70.4510, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Diesel": 1045}},
        {"id": "f13", "nombre": "Copec Taltal", "direccion": "Av. Esmeralda 400", "comuna": "Taltal", "distribuidor": "Copec", "lat": -25.4055, "lng": -70.4830, "precios": {"Gasolina 93": 1310, "Gasolina 95": 1380, "Diesel": 1070}},
        {"id": "f14", "nombre": "Arauco Antofagasta", "direccion": "Av. La Chimba 3200", "comuna": "Antofagasta", "distribuidor": "Arauco", "lat": -23.5950, "lng": -70.3830, "precios": {"Gasolina 93": 1249, "Gasolina 95": 1319, "Diesel": 1009}},
        {"id": "f15", "nombre": "Copec María Elena", "direccion": "Av. Principal 100", "comuna": "María Elena", "distribuidor": "Copec", "lat": -22.3460, "lng": -69.6620, "precios": {"Gasolina 93": 1329, "Gasolina 95": 1399, "Diesel": 1089}},
        {"id": "f16", "nombre": "Shell La Negra", "direccion": "Ruta 5 Norte Km 1370", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.7600, "lng": -70.3400, "precios": {"Gasolina 93": 1295, "Gasolina 95": 1365, "Gasolina 97": 1435, "Diesel": 1055}},
        {"id": "f17", "nombre": "Copec Ruta 5 Carmen Alto", "direccion": "Ruta 5, Carmen Alto", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.4500, "lng": -70.0500, "precios": {"Gasolina 93": 1290, "Gasolina 95": 1360, "Diesel": 1050}},
        {"id": "f18", "nombre": "Terpel Calama Oriente", "direccion": "Av. O'Higgins 4500", "comuna": "Calama", "distribuidor": "Terpel", "lat": -22.4480, "lng": -68.9180, "precios": {"Gasolina 93": 1305, "Gasolina 95": 1375, "Gasolina 97": 1445, "Diesel": 1065}},
        {"id": "f19", "nombre": "ENEX San Pedro de Atacama", "direccion": "Av. Licancabur s/n", "comuna": "San Pedro de Atacama", "distribuidor": "ENEX", "lat": -22.9100, "lng": -68.2000, "precios": {"Gasolina 93": 1349, "Gasolina 95": 1419, "Diesel": 1109}},
        {"id": "f20", "nombre": "Copec Sierra Gorda", "direccion": "Ruta 25, Sierra Gorda", "comuna": "Sierra Gorda", "distribuidor": "Copec", "lat": -22.8930, "lng": -69.3240, "precios": {"Gasolina 93": 1335, "Gasolina 95": 1405, "Diesel": 1095}},
    ]


def load_estaciones():
    """Carga estaciones: primero cache, luego API, luego fallback."""
    # Intentar cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cached = json.load(f)
            if time.time() - cached.get("timestamp", 0) < CACHE_TTL:
                print(f"  [OK] {len(cached['estaciones'])} estaciones desde cache")
                return cached["estaciones"], cached.get("source", "cache")
        except Exception:
            pass

    # Intentar API
    print("  [INFO] Consultando API CNE...")
    raw = fetch_estaciones_cne()
    if raw:
        estaciones = normalize_estaciones(raw)
        if estaciones:
            save_cache(estaciones, "api_cne")
            print(f"  [OK] {len(estaciones)} estaciones desde API CNE")
            return estaciones, "api_cne"

    # Fallback
    estaciones = get_fallback_data()
    save_cache(estaciones, "fallback")
    print(f"  [OK] {len(estaciones)} estaciones (datos de referencia)")
    return estaciones, "fallback"


def save_cache(estaciones, source):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"timestamp": time.time(), "source": source, "estaciones": estaciones}, f)
    except Exception:
        pass


# ── Servidor HTTP ────────────────────────────────────────────────────────────

ESTACIONES = []
DATA_SOURCE = "loading"


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(os.path.dirname(__file__), "static"), **kwargs)

    def do_GET(self):
        global ESTACIONES, DATA_SOURCE
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/estaciones":
            self.send_json({"estaciones": ESTACIONES, "source": DATA_SOURCE, "count": len(ESTACIONES)})

        elif parsed.path == "/api/refresh":
            # Borrar cache para forzar refresh
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
            ESTACIONES, DATA_SOURCE = load_estaciones()
            self.send_json({"estaciones": ESTACIONES, "source": DATA_SOURCE, "count": len(ESTACIONES)})

        else:
            # Servir archivos estáticos
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
    global ESTACIONES, DATA_SOURCE
    print("\n⛽ Bencina Barata - Región de Antofagasta")
    print("=" * 45)
    ESTACIONES, DATA_SOURCE = load_estaciones()
    print(f"\n🌐 Servidor: http://localhost:{PORT}")
    print(f"   Fuente datos: {DATA_SOURCE}")
    print(f"   Estaciones: {len(ESTACIONES)}")
    print(f"\n   Abre http://localhost:{PORT} en tu navegador\n")

    server = http.server.HTTPServer(("", PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Servidor detenido")
        server.server_close()


if __name__ == "__main__":
    main()
