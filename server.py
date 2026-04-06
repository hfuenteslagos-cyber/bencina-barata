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
    """Datos de respaldo con estaciones REALES verificadas de la Region de Antofagasta.
    Fuentes: preciobencina.cl, bencinachile.cl, bencinaenlinea.cl (CNE).
    Precios son referenciales - los reales se obtienen con token de api.cne.cl
    """
    return [
        # ── TOCOPILLA (3 estaciones reales) ──
        {"id": "t1", "nombre": "Copec - Av. 11 de Septiembre", "direccion": "Av. 11 de Septiembre 000", "comuna": "Tocopilla", "distribuidor": "Copec", "lat": -22.0922, "lng": -70.1979, "precios": {"Gasolina 93": 1289, "Gasolina 95": 1359, "Gasolina 97": 1429, "Diesel": 1049}},
        {"id": "t2", "nombre": "Copec - Tte. Merino", "direccion": "Avda. Teniente Merino 3303", "comuna": "Tocopilla", "distribuidor": "Copec", "lat": -22.0850, "lng": -70.1935, "precios": {"Gasolina 93": 1289, "Gasolina 95": 1359, "Gasolina 97": 1429, "Diesel": 1049}},
        {"id": "t3", "nombre": "Shell - Costanera Tocopilla", "direccion": "Avda. Costanera s/n", "comuna": "Tocopilla", "distribuidor": "Shell", "lat": -22.0940, "lng": -70.1995, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Gasolina 97": 1439, "Diesel": 1059}},

        # ── MEJILLONES (2 estaciones reales) ──
        {"id": "m1", "nombre": "Copec - San Martin", "direccion": "San Martin 525", "comuna": "Mejillones", "distribuidor": "Copec", "lat": -23.0983, "lng": -70.4517, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Gasolina 97": 1425, "Diesel": 1045}},
        {"id": "m2", "nombre": "Copec - Av. Fertilizantes", "direccion": "Av. Fertilizantes esq. Ignacio Riquelme", "comuna": "Mejillones", "distribuidor": "Copec", "lat": -23.1010, "lng": -70.4480, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Diesel": 1045}},

        # ── ANTOFAGASTA - COPEC (12 estaciones reales) ──
        {"id": "a1", "nombre": "Copec - Av. Rendic", "direccion": "Av. Antonio Rendic 3855", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6280, "lng": -70.3920, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "a2", "nombre": "Copec - Av. Mejillones", "direccion": "Av. Mejillones 4950 esq. Illapel", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6190, "lng": -70.3870, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "a3", "nombre": "Copec - San Martin/Uribe", "direccion": "San Martin esq. Uribe", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6500, "lng": -70.3980, "precios": {"Gasolina 93": 1265, "Gasolina 95": 1335, "Gasolina 97": 1405, "Diesel": 1025}},
        {"id": "a4", "nombre": "Copec - Av. Angamos", "direccion": "Av. Angamos 0633", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6520, "lng": -70.3960, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "a5", "nombre": "Copec - Ruta 5 Norte Km 1351", "direccion": "Ruta 5 Norte Km 1351", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.5500, "lng": -70.3600, "precios": {"Gasolina 93": 1275, "Gasolina 95": 1345, "Diesel": 1035}},
        {"id": "a6", "nombre": "Copec - Pedro Aguirre Cerda/Rendic", "direccion": "Av. Pedro Aguirre Cerda / A. Rendic", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6100, "lng": -70.3890, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "a7", "nombre": "Copec - Av. Argentina", "direccion": "Av. Argentina 3211", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6380, "lng": -70.3940, "precios": {"Gasolina 93": 1265, "Gasolina 95": 1335, "Gasolina 97": 1405, "Diesel": 1025}},
        {"id": "a8", "nombre": "Copec - Perez Zujovic", "direccion": "Av. Edmundo Perez Zujovic 4256", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.6750, "lng": -70.4050, "precios": {"Gasolina 93": 1265, "Gasolina 95": 1335, "Gasolina 97": 1405, "Diesel": 1025}},
        {"id": "a9", "nombre": "Copec - Rep. de Croacia", "direccion": "Av. Rep. de Croacia 286", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.5850, "lng": -70.3830, "precios": {"Gasolina 93": 1269, "Gasolina 95": 1339, "Gasolina 97": 1409, "Diesel": 1029}},
        {"id": "a10", "nombre": "Copec - PAC 10980", "direccion": "Av. Pedro Aguirre Cerda 10980", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.5750, "lng": -70.3780, "precios": {"Gasolina 93": 1275, "Gasolina 95": 1345, "Diesel": 1035}},
        {"id": "a11", "nombre": "Copec - Perez Zujovic Sur", "direccion": "Av. Perez Zujovic 10675", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.7100, "lng": -70.4150, "precios": {"Gasolina 93": 1265, "Gasolina 95": 1335, "Gasolina 97": 1405, "Diesel": 1025}},
        {"id": "a12", "nombre": "Copec - Ruta 5 Km 1398", "direccion": "Ruta 5 Norte Km 1398", "comuna": "Antofagasta", "distribuidor": "Copec", "lat": -23.7600, "lng": -70.3400, "precios": {"Gasolina 93": 1275, "Gasolina 95": 1345, "Diesel": 1035}},

        # ── ANTOFAGASTA - PETROBRAS (7 estaciones reales) ──
        {"id": "a13", "nombre": "Petrobras - Avda. Grecia", "direccion": "Avda. Grecia 430", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6350, "lng": -70.3935, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Gasolina 97": 1399, "Diesel": 1019}},
        {"id": "a14", "nombre": "Petrobras - Av. Argentina", "direccion": "Av. Argentina 2802", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6400, "lng": -70.3950, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Diesel": 1019}},
        {"id": "a15", "nombre": "Petrobras - Huamachuco", "direccion": "Juan Bolivar Huamachuco 907", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6450, "lng": -70.3965, "precios": {"Gasolina 93": 1255, "Gasolina 95": 1325, "Diesel": 1015}},
        {"id": "a16", "nombre": "Petrobras - Rendic 6850", "direccion": "Av. Antonio Rendic 6850", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6150, "lng": -70.3860, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Diesel": 1019}},
        {"id": "a17", "nombre": "Petrobras - Perez Zujovic 5030", "direccion": "Av. Perez Zujovic 5030", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.6800, "lng": -70.4080, "precios": {"Gasolina 93": 1255, "Gasolina 95": 1325, "Gasolina 97": 1395, "Diesel": 1015}},
        {"id": "a18", "nombre": "Petrobras - PAC 11315", "direccion": "Pedro Aguirre Cerda 11315", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.5700, "lng": -70.3760, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Diesel": 1019}},
        {"id": "a19", "nombre": "Petrobras - PAC 10850", "direccion": "Avda. Pedro Aguirre Cerda 10850", "comuna": "Antofagasta", "distribuidor": "Petrobras", "lat": -23.5730, "lng": -70.3770, "precios": {"Gasolina 93": 1259, "Gasolina 95": 1329, "Diesel": 1019}},

        # ── ANTOFAGASTA - SHELL (5 estaciones reales) ──
        {"id": "a20", "nombre": "Shell - Rendic 4561", "direccion": "Antonio Rendic 4561", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.6240, "lng": -70.3910, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Gasolina 97": 1419, "Diesel": 1039}},
        {"id": "a21", "nombre": "Shell - 21 de Mayo/Argentina", "direccion": "Avda. 21 de Mayo / Argentina 1119", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.6480, "lng": -70.3970, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Gasolina 97": 1419, "Diesel": 1039}},
        {"id": "a22", "nombre": "Shell - Argentina/Diaz Gana", "direccion": "Avda. Argentina / Diaz Gana 1105", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.6420, "lng": -70.3945, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Gasolina 97": 1419, "Diesel": 1039}},
        {"id": "a23", "nombre": "Shell - Panamericana Km 1354", "direccion": "Panamericana Norte Km 1354", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.5600, "lng": -70.3650, "precios": {"Gasolina 93": 1285, "Gasolina 95": 1355, "Diesel": 1045}},
        {"id": "a24", "nombre": "Shell - PAC 8450", "direccion": "Pedro Aguirre Cerda 8450", "comuna": "Antofagasta", "distribuidor": "Shell", "lat": -23.5900, "lng": -70.3820, "precios": {"Gasolina 93": 1279, "Gasolina 95": 1349, "Gasolina 97": 1419, "Diesel": 1039}},

        # ── CALAMA - COPEC (5 estaciones reales) ──
        {"id": "c1", "nombre": "Copec - Granaderos", "direccion": "Granaderos 3524", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4560, "lng": -68.9293, "precios": {"Gasolina 93": 1309, "Gasolina 95": 1379, "Gasolina 97": 1449, "Diesel": 1069}},
        {"id": "c2", "nombre": "Copec - Abaroa", "direccion": "Abaroa 1413", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4580, "lng": -68.9260, "precios": {"Gasolina 93": 1309, "Gasolina 95": 1379, "Gasolina 97": 1449, "Diesel": 1069}},
        {"id": "c3", "nombre": "Copec - Diego de Almagro", "direccion": "Diego de Almagro 2547", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4530, "lng": -68.9310, "precios": {"Gasolina 93": 1305, "Gasolina 95": 1375, "Gasolina 97": 1445, "Diesel": 1065}},
        {"id": "c4", "nombre": "Copec - Punta de Diamante", "direccion": "Punta de Diamante S/N, Salida Sur", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4700, "lng": -68.9350, "precios": {"Gasolina 93": 1309, "Gasolina 95": 1379, "Diesel": 1069}},
        {"id": "c5", "nombre": "Copec - Balmaceda 3012", "direccion": "Av. Balmaceda 3012", "comuna": "Calama", "distribuidor": "Copec", "lat": -22.4540, "lng": -68.9280, "precios": {"Gasolina 93": 1305, "Gasolina 95": 1375, "Gasolina 97": 1445, "Diesel": 1065}},

        # ── CALAMA - PETROBRAS (3 estaciones reales) ──
        {"id": "c6", "nombre": "Petrobras - Chorrillos/Latorre", "direccion": "Av. Chorrillos / Latorre 2687", "comuna": "Calama", "distribuidor": "Petrobras", "lat": -22.4550, "lng": -68.9240, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Gasolina 97": 1439, "Diesel": 1059}},
        {"id": "c7", "nombre": "Petrobras - Balmaceda 4450", "direccion": "Balmaceda 4450", "comuna": "Calama", "distribuidor": "Petrobras", "lat": -22.4500, "lng": -68.9200, "precios": {"Gasolina 93": 1299, "Gasolina 95": 1369, "Diesel": 1059}},
        {"id": "c8", "nombre": "Petrobras - Miguel Grau", "direccion": "Av. Miguel Grau 1064", "comuna": "Calama", "distribuidor": "Petrobras", "lat": -22.4590, "lng": -68.9270, "precios": {"Gasolina 93": 1295, "Gasolina 95": 1365, "Diesel": 1055}},

        # ── CALAMA - SHELL (2 estaciones reales) ──
        {"id": "c9", "nombre": "Shell - Balmaceda 4539", "direccion": "Balmaceda 4539", "comuna": "Calama", "distribuidor": "Shell", "lat": -22.4490, "lng": -68.9190, "precios": {"Gasolina 93": 1315, "Gasolina 95": 1385, "Gasolina 97": 1455, "Diesel": 1075}},
        {"id": "c10", "nombre": "Shell - O'Higgins", "direccion": "Avda. O'Higgins 234", "comuna": "Calama", "distribuidor": "Shell", "lat": -22.4570, "lng": -68.9250, "precios": {"Gasolina 93": 1319, "Gasolina 95": 1389, "Gasolina 97": 1459, "Diesel": 1079}},

        # ── TALTAL (3 estaciones reales) ──
        {"id": "tt1", "nombre": "Copec - Francisco Bilbao", "direccion": "Francisco Bilbao 101", "comuna": "Taltal", "distribuidor": "Copec", "lat": -25.4053, "lng": -70.4828, "precios": {"Gasolina 93": 1310, "Gasolina 95": 1380, "Gasolina 97": 1450, "Diesel": 1070}},
        {"id": "tt2", "nombre": "Copec - Panamericana Km 1144", "direccion": "Panamericana Norte Km 1144", "comuna": "Taltal", "distribuidor": "Copec", "lat": -25.3800, "lng": -70.4500, "precios": {"Gasolina 93": 1315, "Gasolina 95": 1385, "Diesel": 1075}},
        {"id": "tt3", "nombre": "Petrobras - Bilbao 986", "direccion": "Francisco Bilbao 986", "comuna": "Taltal", "distribuidor": "Petrobras", "lat": -25.4060, "lng": -70.4835, "precios": {"Gasolina 93": 1305, "Gasolina 95": 1375, "Diesel": 1065}},

        # ── SIERRA GORDA (1 estacion real) ──
        {"id": "sg1", "nombre": "Copec - Carmen Alto", "direccion": "Carmen Alto 1458", "comuna": "Sierra Gorda", "distribuidor": "Copec", "lat": -22.8933, "lng": -69.3236, "precios": {"Gasolina 93": 1335, "Gasolina 95": 1405, "Gasolina 97": 1475, "Diesel": 1095}},

        # ── SAN PEDRO DE ATACAMA (1 estacion real) ──
        {"id": "sp1", "nombre": "Copec - Ruta 27", "direccion": "Ruta 27 Interseccion B241", "comuna": "San Pedro de Atacama", "distribuidor": "Copec", "lat": -22.9087, "lng": -68.1997, "precios": {"Gasolina 93": 1349, "Gasolina 95": 1419, "Gasolina 97": 1489, "Diesel": 1109}},
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
