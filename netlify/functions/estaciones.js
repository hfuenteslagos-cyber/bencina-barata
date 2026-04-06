// Netlify serverless function - scrapea preciobencina.cl
const https = require('https');
const http = require('http');

const SCRAPE_URL = 'https://preciobencina.cl/bencineras-en-region-de-antofagasta.php';

// Cache en memoria (persiste entre invocaciones en caliente)
let cache = { data: null, timestamp: 0 };
const CACHE_TTL = 3600000; // 1 hora en ms

exports.handler = async (event) => {
  const forceRefresh = event.queryStringParameters && event.queryStringParameters.refresh === '1';
  const now = Date.now();

  // Devolver cache si es valido
  if (!forceRefresh && cache.data && (now - cache.timestamp) < CACHE_TTL) {
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ ...cache.data, cached: true }),
    };
  }

  try {
    const html = await fetchPage(SCRAPE_URL);
    const estaciones = parseMarkers(html);

    if (estaciones.length >= 5) {
      cache = {
        data: { estaciones, source: 'preciobencina.cl', count: estaciones.length, updated: now },
        timestamp: now,
      };
      return {
        statusCode: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify(cache.data),
      };
    }
  } catch (err) {
    console.error('Scrape error:', err.message);
  }

  // Fallback
  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    body: JSON.stringify({ estaciones: getFallback(), source: 'fallback', count: getFallback().length }),
  };
};

function fetchPage(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'text/html',
      },
      timeout: 12000,
    }, (res) => {
      // Follow redirects
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return fetchPage(res.headers.location).then(resolve).catch(reject);
      }
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

function parseMarkers(html) {
  const estaciones = [];
  // L.marker([lat, lng], ...).bindPopup('...')
  const re = /L\.marker\(\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\].*?\.bindPopup\('(.*?)'\)/gs;
  let match;
  let idx = 0;

  while ((match = re.exec(html)) !== null) {
    try {
      const lat = parseFloat(match[1]);
      const lng = parseFloat(match[2]);
      let popup = match[3].replace(/\\'/g, "'").replace(/\\n/g, "\n");

      // Brand
      const brandM = popup.match(/<h3[^>]*>(.*?)<\/h3>/s);
      const brandRaw = brandM ? stripHtml(brandM[1]) : 'Desconocida';

      // Address
      const addrM = popup.match(/<h4[^>]*>.*?<\/i>\s*(.*?)<\/h4>/s);
      let direccion = addrM ? stripHtml(addrM[1]).trim() : '';
      let comuna = '';

      const known = ['Antofagasta','Tocopilla','Calama','Mejillones','Taltal','San Pedro de Atacama','Sierra Gorda','Maria Elena'];
      if (direccion.includes(',')) {
        const parts = direccion.split(',');
        const last = parts[parts.length - 1].trim();
        if (known.some(c => last.toLowerCase().includes(c.toLowerCase()))) {
          comuna = last;
          direccion = parts.slice(0, -1).join(',').trim();
        } else {
          comuna = guessComuna(lat, lng);
        }
      } else {
        comuna = guessComuna(lat, lng);
      }

      // Prices
      const precios = {};
      const p93 = popup.match(/(?:Bencina|Gasolina)\s*93.*?\$\s*([\d.,]+)/);
      if (p93) precios['Gasolina 93'] = parsePrice(p93[1]);
      const p95 = popup.match(/(?:Bencina|Gasolina)\s*95.*?\$\s*([\d.,]+)/);
      if (p95) precios['Gasolina 95'] = parsePrice(p95[1]);
      const p97 = popup.match(/(?:Bencina|Gasolina)\s*97.*?\$\s*([\d.,]+)/);
      if (p97) precios['Gasolina 97'] = parsePrice(p97[1]);
      const pd = popup.match(/[Dd]iesel.*?\$\s*([\d.,]+)/);
      if (pd) precios['Diesel'] = parsePrice(pd[1]);
      const pk = popup.match(/[Kk]erosene.*?\$\s*([\d.,]+)/);
      if (pk) precios['Kerosene'] = parsePrice(pk[1]);

      const idM = popup.match(/detalles-bencinera\.php\?i=(\w+)/);
      const id = idM ? idM[1] : `s${++idx}`;

      const distribuidor = normalizeBrand(brandRaw);

      if (Object.keys(precios).length > 0 && lat !== 0) {
        estaciones.push({
          id, nombre: `${distribuidor} - ${direccion}`, direccion, comuna,
          distribuidor, lat, lng, precios,
        });
      }
    } catch (e) { continue; }
  }
  return estaciones;
}

function stripHtml(s) { return s.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#039;/g, "'").replace(/&quot;/g, '"').trim(); }

function parsePrice(s) {
  const n = parseInt(s.replace(/\./g, '').replace(/,/g, ''));
  return n > 100 ? n : 0;
}

function normalizeBrand(b) {
  const u = b.toUpperCase();
  if (u.includes('COPEC')) return 'Copec';
  if (u.includes('SHELL')) return 'Shell';
  if (u.includes('PETROBRAS') || u.includes('ENEX')) return 'Petrobras';
  if (u.includes('TERPEL')) return 'Terpel';
  if (u.includes('ARAUCO')) return 'Arauco';
  return b.trim();
}

function guessComuna(lat, lng) {
  if (lat > -22.15 && lat < -22.02 && lng > -70.25 && lng < -70.15) return 'Tocopilla';
  if (lat > -23.15 && lat < -23.05 && lng > -70.50 && lng < -70.40) return 'Mejillones';
  if (lat > -23.80 && lat < -23.55 && lng > -70.45 && lng < -70.30) return 'Antofagasta';
  if (lat > -22.50 && lat < -22.40 && lng > -69.00 && lng < -68.85) return 'Calama';
  if (lat > -25.45 && lat < -25.35 && lng > -70.55 && lng < -70.40) return 'Taltal';
  if (lat > -22.95 && lat < -22.85 && lng > -68.25 && lng < -68.15) return 'San Pedro de Atacama';
  if (lat > -22.95 && lat < -22.85 && lng > -69.40 && lng < -69.25) return 'Sierra Gorda';
  return 'Antofagasta';
}

function getFallback() {
  return [
    {id:"t1",nombre:"Copec - Av. 11 de Septiembre",direccion:"Av. 11 de Septiembre 000",comuna:"Tocopilla",distribuidor:"Copec",lat:-22.0922,lng:-70.1979,precios:{"Gasolina 93":1238,"Gasolina 95":1273,"Diesel":1053}},
    {id:"a1",nombre:"Copec - Av. Rendic",direccion:"Av. Antonio Rendic 3855",comuna:"Antofagasta",distribuidor:"Copec",lat:-23.6280,lng:-70.3920,precios:{"Gasolina 93":1236,"Gasolina 95":1271,"Gasolina 97":1301,"Diesel":1047}},
    {id:"a2",nombre:"Shell - PAC",direccion:"Av. Pedro Aguirre Cerda 10615",comuna:"Antofagasta",distribuidor:"Shell",lat:-23.5780,lng:-70.3790,precios:{"Gasolina 93":1235,"Gasolina 95":1270,"Gasolina 97":1300,"Diesel":1046}},
    {id:"c1",nombre:"Copec - Granaderos",direccion:"Granaderos 3524",comuna:"Calama",distribuidor:"Copec",lat:-22.4560,lng:-68.9293,precios:{"Gasolina 93":1247,"Gasolina 95":1280,"Gasolina 97":1309,"Diesel":1066}},
  ];
}
