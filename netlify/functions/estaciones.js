// Netlify serverless function - API oficial CNE (Comision Nacional de Energia)
const https = require('https');
const zlib = require('zlib');

const CNE_LOGIN_URL = 'https://api.cne.cl/api/login';
const CNE_ESTACIONES_URL = 'https://api.cne.cl/api/v4/estaciones';
// Sin filtro de region - todo Chile

// Cache en memoria (persiste entre invocaciones en caliente)
let cache = { data: null, timestamp: 0 };
const CACHE_TTL = 3600000; // 1 hora en ms

// Token cache
let tokenCache = { token: null, timestamp: 0 };
const TOKEN_TTL = 3500000; // ~58 min (token dura 1hr)

exports.handler = async (event) => {
  const headers = { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' };
  const forceRefresh = event.queryStringParameters && event.queryStringParameters.refresh === '1';
  const now = Date.now();

  // Devolver cache si es valido
  if (!forceRefresh && cache.data && (now - cache.timestamp) < CACHE_TTL) {
    return { statusCode: 200, headers, body: JSON.stringify({ ...cache.data, cached: true }) };
  }

  try {
    // 1. Obtener token
    const token = await getToken();

    // 2. Obtener estaciones
    const raw = await fetchJSON(CNE_ESTACIONES_URL, token);

    // 3. Filtrar Region de Antofagasta y mapear
    const estaciones = parseEstaciones(raw);

    if (estaciones.length >= 3) {
      cache = {
        data: { estaciones, source: 'CNE (api.cne.cl)', count: estaciones.length, updated: now },
        timestamp: now,
      };
      return { statusCode: 200, headers, body: JSON.stringify(cache.data) };
    }
  } catch (err) {
    console.error('CNE API error:', err.message);
  }

  // Fallback si la API falla
  return {
    statusCode: 200, headers,
    body: JSON.stringify({ estaciones: getFallback(), source: 'fallback', count: getFallback().length }),
  };
};

async function getToken() {
  const now = Date.now();
  if (tokenCache.token && (now - tokenCache.timestamp) < TOKEN_TTL) {
    return tokenCache.token;
  }

  const email = process.env.CNE_EMAIL;
  const password = process.env.CNE_PASSWORD;

  if (!email || !password) {
    throw new Error('CNE_EMAIL y CNE_PASSWORD no configurados en variables de entorno');
  }

  const body = JSON.stringify({ email, password });
  const data = await postJSON(CNE_LOGIN_URL, body);

  if (!data.token) throw new Error('Login CNE fallido: ' + JSON.stringify(data));

  tokenCache = { token: data.token, timestamp: now };
  return data.token;
}

function postJSON(url, body) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = https.request({
      hostname: parsed.hostname,
      path: parsed.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
      timeout: 15000,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('JSON parse error: ' + data.substring(0, 200))); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.write(body);
    req.end();
  });
}

function fetchJSON(url, token) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = https.request({
      hostname: parsed.hostname,
      path: parsed.pathname + parsed.search,
      method: 'GET',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate',
      },
      timeout: 20000,
    }, (res) => {
      const chunks = [];
      const encoding = res.headers['content-encoding'];
      const stream = (encoding === 'gzip') ? res.pipe(zlib.createGunzip()) :
                     (encoding === 'deflate') ? res.pipe(zlib.createInflate()) : res;
      stream.on('data', chunk => chunks.push(chunk));
      stream.on('end', () => {
        try {
          const data = Buffer.concat(chunks).toString('utf8');
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error('JSON parse error'));
        }
      });
      stream.on('error', reject);
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.end();
  });
}

function parseEstaciones(raw) {
  const estaciones = [];

  // La API puede devolver un array directo o un objeto con propiedad
  const lista = Array.isArray(raw) ? raw : (raw.data || raw.estaciones || []);

  for (const e of lista) {
    try {
      const ubi = e.ubicacion || {};
      const region = ubi.nombre_region || '';

      const lat = parseFloat(ubi.latitud || ubi.lat || 0);
      const lng = parseFloat(ubi.longitud || ubi.lng || ubi.lon || 0);
      if (lat === 0 || lng === 0) continue;

      const distribuidor = normalizeBrand(
        (e.distribuidor && (e.distribuidor.marca || e.distribuidor.nombre)) ||
        e.distribuidor_marca || e.marca || 'Desconocida'
      );

      const direccion = ubi.direccion || ubi.calle || '';
      const comuna = ubi.nombre_comuna || ubi.comuna || '';
      const regionNombre = region;
      const id = e.codigo || e.id || `s${estaciones.length}`;

      // Precios - claves: 93/A93, 95/A95, 97/A97, DI/ADI, KE, GLP
      const precios = {};
      const p = e.precios || {};

      const g93 = p['93'] || p['A93'];
      const g95 = p['95'] || p['A95'];
      const g97 = p['97'] || p['A97'];
      const di = p['DI'] || p['ADI'];
      const ke = p['KE'];

      if (g93 && g93.precio) precios['Gasolina 93'] = Math.round(parseFloat(g93.precio));
      if (g95 && g95.precio) precios['Gasolina 95'] = Math.round(parseFloat(g95.precio));
      if (g97 && g97.precio) precios['Gasolina 97'] = Math.round(parseFloat(g97.precio));
      if (di && di.precio) precios['Diesel'] = Math.round(parseFloat(di.precio));
      if (ke && ke.precio) precios['Kerosene'] = Math.round(parseFloat(ke.precio));

      if (Object.keys(precios).length > 0) {
        estaciones.push({
          id, nombre: `${distribuidor} - ${direccion}`, direccion, comuna, region: regionNombre,
          distribuidor, lat, lng, precios,
        });
      }
    } catch (err) { continue; }
  }
  return estaciones;
}

function normalizeBrand(b) {
  const u = String(b).toUpperCase();
  if (u.includes('COPEC')) return 'Copec';
  if (u.includes('SHELL')) return 'Shell';
  if (u.includes('PETROBRAS') || u.includes('ENEX')) return 'Petrobras';
  if (u.includes('TERPEL')) return 'Terpel';
  if (u.includes('ARAUCO')) return 'Arauco';
  return String(b).trim();
}

function guessComuna(lat, lng) {
  if (lat > -22.15 && lat < -22.02 && lng > -70.25 && lng < -70.15) return 'Tocopilla';
  if (lat > -23.15 && lat < -23.05 && lng > -70.50 && lng < -70.40) return 'Mejillones';
  if (lat > -23.80 && lat < -23.55 && lng > -70.45 && lng < -70.30) return 'Antofagasta';
  if (lat > -22.50 && lat < -22.40 && lng > -69.00 && lng < -68.85) return 'Calama';
  if (lat > -25.45 && lat < -25.35 && lng > -70.55 && lng < -70.40) return 'Taltal';
  if (lat > -22.95 && lat < -22.85 && lng > -68.25 && lng < -68.15) return 'San Pedro de Atacama';
  return 'Antofagasta';
}

function getFallback() {
  return [
    {id:"t1",nombre:"Copec - Av. 11 de Septiembre",direccion:"Av. 11 de Septiembre 000",comuna:"Tocopilla",distribuidor:"Copec",lat:-22.0922,lng:-70.1979,precios:{"Gasolina 93":1513,"Gasolina 95":1564,"Diesel":1100}},
    {id:"a1",nombre:"Copec - Av. Rendic",direccion:"Av. Antonio Rendic 3855",comuna:"Antofagasta",distribuidor:"Copec",lat:-23.6280,lng:-70.3920,precios:{"Gasolina 93":1510,"Gasolina 95":1560,"Gasolina 97":1626,"Diesel":1095}},
    {id:"a2",nombre:"Shell - PAC",direccion:"Av. Pedro Aguirre Cerda 10615",comuna:"Antofagasta",distribuidor:"Shell",lat:-23.5780,lng:-70.3790,precios:{"Gasolina 93":1515,"Gasolina 95":1565,"Gasolina 97":1630,"Diesel":1098}},
    {id:"c1",nombre:"Copec - Granaderos",direccion:"Granaderos 3524",comuna:"Calama",distribuidor:"Copec",lat:-22.4560,lng:-68.9293,precios:{"Gasolina 93":1520,"Gasolina 95":1570,"Gasolina 97":1635,"Diesel":1105}},
  ];
}
