import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { getUbiClient } from './ubi';
import { getApiUrl } from './config';

function App() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [ubiInfo, setUbiInfo] = useState(null);

  const ubiClient = getUbiClient();

  useEffect(() => {
    // Update UBI status display
    const interval = setInterval(() => {
      setUbiInfo(ubiClient.getTrackingInfo());
    }, 1000);
    return () => clearInterval(interval);
  }, [ubiClient]);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;

    setLoading(true);
    setResults([]);
    try {
      const resp = await axios.post(`${getApiUrl()}/api/search`, { query, size: 10 });
      const hits = resp.data.hits || [];
      setResults(hits);

      // Track query with UBI
      const hitIds = hits.map((h) => h.id);
      await ubiClient.trackQuery(query, hitIds);

      // Track impression
      if (hitIds.length > 0) {
        ubiClient.trackImpression(hitIds);
      }
    } catch (err) {
      console.error('Search failed:', err);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, ubiClient]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch();
  };

  const handleResultClick = (item, position) => {
    ubiClient.trackClick(item.id, position + 1, item.name || item.title);
    ubiClient.trackView(item.id, item.name || item.title);
  };

  const handleResultHover = (item) => {
    ubiClient.trackHover(item.id, item.name || item.title);
  };

  const handleAddToCart = (e, item) => {
    e.stopPropagation();
    ubiClient.trackAddToCart(item.id, 1, item.name || item.title);
    alert(`Added "${item.name || item.title}" to cart!`);
  };

  return (
    <div className="app">
      <h1>🔍 UBI Sample Search</h1>

      <div className="search-box">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search products..."
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      <div className="results">
        {results.length === 0 && !loading && (
          <div className="status">Enter a search term to find products</div>
        )}

        {results.map((item, idx) => (
          <div
            key={item.id}
            className="result-item"
            onClick={() => handleResultClick(item, idx)}
            onMouseEnter={() => handleResultHover(item)}
          >
            <h3>{item.name || item.title || item.id}</h3>
            <p>{item.description || 'No description'}</p>
            <div className="meta">
              {item.brand && <span>Brand: {item.brand} | </span>}
              {item.category && <span>Category: {item.category} | </span>}
              {item.price && <span>Price: ${item.price}</span>}
            </div>
            <button
              style={{ marginTop: '10px', padding: '6px 12px' }}
              onClick={(e) => handleAddToCart(e, item)}
            >
              Add to Cart
            </button>
          </div>
        ))}
      </div>

      {ubiInfo && (
        <div className="ubi-status">
          UBI: {ubiInfo.queuedEvents} events queued
          <br />
          Query: {ubiInfo.queryId?.slice(0, 8) || 'none'}...
        </div>
      )}
    </div>
  );
}

export default App;
