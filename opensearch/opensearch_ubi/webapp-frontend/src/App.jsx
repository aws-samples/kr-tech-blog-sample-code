import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { getUbiClient } from './ubi';
import { getApiUrl } from './config';

const EVENT_COLORS = {
  on_search: '#3b82f6',
  search: '#3b82f6',
  click: '#22c55e',
  view: '#22c55e',
  add_to_cart: '#f97316',
  impression: '#8b5cf6',
  product_hover: '#6b7280',
};

const getEventColor = (type) => EVENT_COLORS[type] || '#6b7280';

function ToastContainer({ toasts, onDismiss }) {
  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast ${toast.exiting ? 'toast-exit' : 'toast-enter'}`}
          style={{ '--event-color': getEventColor(toast.type) }}
          onClick={() => onDismiss(toast.id)}
        >
          <div className="toast-indicator" />
          <div className="toast-content">
            <span className="toast-type">{toast.type}</span>
            <span className="toast-message">{toast.description}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function UbiBadge({ eventCount, recentEvents, expanded, onToggle }) {
  return (
    <div className={`ubi-badge ${expanded ? 'expanded' : ''}`} onClick={onToggle}>
      <div className="ubi-badge-dot" />
      <span className="ubi-badge-count">{eventCount}</span>
      {expanded && recentEvents.length > 0 && (
        <div className="ubi-badge-details">
          {recentEvents.slice(0, 5).map((evt, idx) => (
            <div key={idx} className="ubi-badge-item">
              <span
                className="ubi-badge-type"
                style={{ color: getEventColor(evt.type) }}
              >
                {evt.type}
              </span>
              <span className="ubi-badge-desc">{evt.description}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function App() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [eventHistory, setEventHistory] = useState([]);
  const [badgeExpanded, setBadgeExpanded] = useState(false);
  const toastIdRef = useRef(0);

  const ubiClient = getUbiClient();

  useEffect(() => {
    const unsubscribe = ubiClient.onEvent((event) => {
      const id = ++toastIdRef.current;
      const newToast = { id, ...event, exiting: false };

      setToasts((prev) => {
        const updated = [...prev, newToast];
        return updated.slice(-3);
      });

      setEventHistory((prev) => [event, ...prev].slice(0, 20));

      setTimeout(() => {
        setToasts((prev) =>
          prev.map((t) => (t.id === id ? { ...t, exiting: true } : t))
        );
        setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== id));
        }, 300);
      }, 2000);
    });

    return () => unsubscribe();
  }, [ubiClient]);

  const dismissToast = useCallback((id) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, exiting: true } : t))
    );
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 300);
  }, []);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;

    setLoading(true);
    setResults([]);
    try {
      const resp = await axios.post(`${getApiUrl()}/api/search`, { query, size: 10 });
      const hits = resp.data.hits || [];
      setResults(hits);

      const hitIds = hits.map((h) => h.id);
      const resultCount = resp.data.total || hits.length;
      await ubiClient.trackQuery(query, hitIds, resultCount);

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
    ubiClient.trackClick(item.id, position + 1, item.name || item.title, item);
    ubiClient.trackView(item.id, item.name || item.title, item);
  };

  const handleResultHover = (item) => {
    ubiClient.trackHover(item.id, item.name || item.title, item);
  };

  const handleAddToCart = (e, item) => {
    e.stopPropagation();
    ubiClient.trackAddToCart(item.id, 1, item.name || item.title, item);
    alert(`Added "${item.name || item.title}" to cart!`);
  };

  return (
    <div className="app">
      <h1>UBI Sample Search</h1>

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

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <UbiBadge
        eventCount={eventHistory.length}
        recentEvents={eventHistory}
        expanded={badgeExpanded}
        onToggle={() => setBadgeExpanded((prev) => !prev)}
      />
    </div>
  );
}

export default App;
