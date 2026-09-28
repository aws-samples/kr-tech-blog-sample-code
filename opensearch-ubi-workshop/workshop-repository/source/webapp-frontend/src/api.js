import { getUbi } from './ubi.js';

async function post(path, body) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json();
}

async function get(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json();
}

export async function searchProducts({ query, size = 24, category, brand, sort = 'relevance', useLtr = false }) {
  const ubi = getUbi();
  const data = await post('/api/search', {
    query: query || '',
    size,
    category: category || null,
    brand: brand || null,
    sort,
    use_ltr: useLtr,
    client_id: ubi.clientId,
    session_id: ubi.sessionId,
  });
  if ((query || '').trim()) {
    ubi.setQueryId(data.query_id);
    ubi.trackImpression(data.hits.map((h) => h.id));
  }
  return data;
}

export const fetchCategories = () => get('/api/categories');
export const fetchConfig = () => get('/api/config');
export const fetchProduct = (id) => get(`/api/products/${encodeURIComponent(id)}`);
