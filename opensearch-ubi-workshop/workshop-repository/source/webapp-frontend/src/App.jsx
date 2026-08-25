import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchCategories, fetchConfig, searchProducts } from './api.js';
import { getUbi } from './ubi.js';

const KRW = (v) => (v ?? 0).toLocaleString('ko-KR') + '원';

function ProductImage({ product, size = 'card' }) {
  return (
    <div className={`pimg pimg-${size}`}>
      <span>{product.emoji || '📦'}</span>
    </div>
  );
}

function Stars({ rating }) {
  const full = Math.round(rating || 0);
  return (
    <span className="stars" title={`평점 ${rating}`}>
      {'★'.repeat(full)}{'☆'.repeat(5 - full)} <em>{rating?.toFixed(1)}</em>
    </span>
  );
}

function ProductCard({ product, position, onOpen, onQuickCart }) {
  return (
    <div className="card" onClick={() => onOpen(product, position)}>
      <div className="card-pos">#{position + 1}</div>
      <ProductImage product={product} />
      <div className="card-body">
        <div className="card-brand">{product.brand} · {product.category}</div>
        <div className="card-name">{product.name}</div>
        <div className="card-rating">
          <Stars rating={product.rating} />
          <span className="reviews">리뷰 {product.review_count?.toLocaleString()}</span>
        </div>
        <div className="card-price-row">
          <div>
            <div className="card-price">{KRW(product.price)}</div>
            <div className="card-ship">무료배송</div>
          </div>
          <button
            className="btn-mini-cart"
            title="장바구니 담기"
            onClick={(e) => { e.stopPropagation(); onQuickCart(product, position); }}
          >🛒</button>
        </div>
        {product.tags?.length > 0 && (
          <div className="card-tags">{product.tags.slice(0, 3).map((t) => <span key={t}>{t}</span>)}</div>
        )}
      </div>
    </div>
  );
}

function ProductModal({ product, onClose, onAddCart, onBuyNow }) {
  if (!product) return null;
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-grid">
          <ProductImage product={product} size="big" />
          <div className="modal-info">
            <div className="card-brand">{product.brand} · {product.category}</div>
            <h2>{product.name}</h2>
            <div className="card-rating">
              <Stars rating={product.rating} />
              <span className="reviews">리뷰 {product.review_count?.toLocaleString()}개</span>
            </div>
            <div className="modal-price">{KRW(product.price)}</div>
            <table className="spec-table">
              <tbody>
                {Object.entries(product.specs || {}).map(([k, v]) => (
                  <tr key={k}><th>{k}</th><td>{v}</td></tr>
                ))}
                <tr><th>재고</th><td>{product.stock > 0 ? `${product.stock}개` : '품절'}</td></tr>
                <tr><th>출시</th><td>{product.release_year}년</td></tr>
              </tbody>
            </table>
            <p className="modal-desc">{product.description}</p>
            <div className="modal-actions">
              <button className="btn-cart" onClick={() => onAddCart(product)}>장바구니</button>
              <button className="btn-buy" onClick={() => onBuyNow(product)}>바로구매</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CartDrawer({ open, items, onClose, onCheckout, onRemove }) {
  const total = items.reduce((s, it) => s + it.product.price * it.qty, 0);
  return (
    <div className={`drawer ${open ? 'open' : ''}`}>
      <div className="drawer-head">
        <h3>장바구니</h3>
        <button className="modal-close" onClick={onClose}>✕</button>
      </div>
      {items.length === 0 ? (
        <p className="drawer-empty">장바구니가 비어 있습니다</p>
      ) : (
        <>
          <div className="drawer-items">
            {items.map((it) => (
              <div className="drawer-item" key={it.product.id}>
                <ProductImage product={it.product} size="mini" />
                <div className="drawer-item-info">
                  <div className="drawer-item-name">{it.product.name}</div>
                  <div className="drawer-item-price">{KRW(it.product.price)} × {it.qty}</div>
                </div>
                <button className="btn-remove" onClick={() => onRemove(it.product.id)}>삭제</button>
              </div>
            ))}
          </div>
          <div className="drawer-total">합계 <strong>{KRW(total)}</strong></div>
          <button className="btn-buy drawer-checkout" onClick={onCheckout}>결제하기</button>
        </>
      )}
    </div>
  );
}

function UbiDebugPanel({ ltrModel }) {
  const [events, setEvents] = useState([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const off = getUbi().onEvent((e) =>
      setEvents((prev) => [
        { t: new Date().toLocaleTimeString('ko-KR'), name: e.action_name, msg: e.message },
        ...prev.slice(0, 19),
      ]),
    );
    return off;
  }, []);
  return (
    <div className={`ubi-panel ${open ? 'open' : ''}`}>
      <button className="ubi-toggle" onClick={() => setOpen(!open)}>
        📡 UBI {events.length > 0 && <b>{events.length}</b>}
      </button>
      {open && (
        <div className="ubi-log">
          <div className="ubi-log-head">
            UBI 이벤트 스트림 → OSI → OpenSearch
            {ltrModel && <div className="ubi-model">LTR 모델: {ltrModel}</div>}
          </div>
          {events.length === 0 && <div className="ubi-row">아직 이벤트가 없습니다. 검색하고 클릭해 보세요!</div>}
          {events.map((e, i) => (
            <div className="ubi-row" key={i}>
              <span className={`ubi-badge ubi-${e.name}`}>{e.name}</span>
              <span className="ubi-msg">{e.msg}</span>
              <span className="ubi-time">{e.t}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const HOT_KEYWORDS = ['노트북', '삼성 갤럭시', '무선 이어폰', '게이밍 모니터', '로봇청소기', '아이폰', '4K TV', '에어팟', '키보드', '공기청정기'];

export default function App() {
  const ubi = useMemo(() => getUbi(), []);
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState([]);
  const [total, setTotal] = useState(0);
  const [tookMs, setTookMs] = useState(null);
  const [ltrUsed, setLtrUsed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState('');
  const [sort, setSort] = useState('relevance');
  const [useLtr, setUseLtr] = useState(false);
  const [ltrModel, setLtrModel] = useState(null);
  const [modal, setModal] = useState(null);
  const [cart, setCart] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const showToast = (msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2500);
  };

  const runSearch = async ({ q = query, cat = category, srt = sort, ltr = useLtr } = {}) => {
    setLoading(true);
    try {
      const data = await searchProducts({ query: q, category: cat, sort: srt, useLtr: ltr });
      setHits(data.hits);
      setTotal(data.total);
      setTookMs(data.took_ms);
      setLtrUsed(data.ltr_used);
    } catch (e) {
      showToast('검색 오류: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runSearch({ q: '' });
    fetchCategories().then((d) => setCategories(d.categories)).catch(() => {});
    fetchConfig().then((d) => setLtrModel(d.ltr_model)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = (e) => {
    e?.preventDefault();
    setQuery(input);
    runSearch({ q: input });
  };

  const searchKeyword = (kw) => {
    setInput(kw);
    setQuery(kw);
    runSearch({ q: kw });
  };

  const selectCategory = (cat) => {
    const next = cat === category ? '' : cat;
    setCategory(next);
    runSearch({ cat: next });
  };

  const toggleLtr = () => {
    const next = !useLtr;
    setUseLtr(next);
    if (query) runSearch({ ltr: next });
  };

  const openProduct = (product, position) => {
    ubi.trackClick(product.id, position, product);
    ubi.trackView(product.id, product);
    setModal(product);
  };

  const addToCart = (product, { fromCard = false, position = null } = {}) => {
    ubi.trackAddToCart(product.id, 1, product);
    setCart((prev) => {
      const found = prev.find((it) => it.product.id === product.id);
      if (found) return prev.map((it) => it.product.id === product.id ? { ...it, qty: it.qty + 1 } : it);
      return [...prev, { product, qty: 1 }];
    });
    showToast(`🛒 ${product.name} 담았습니다`);
  };

  const buyNow = (product) => {
    ubi.trackPurchase(product.id, 1, product);
    setModal(null);
    showToast(`✅ 주문 완료: ${product.name}`);
  };

  const checkout = () => {
    cart.forEach((it) => ubi.trackPurchase(it.product.id, it.qty, it.product));
    setCart([]);
    setCartOpen(false);
    showToast('✅ 결제가 완료되었습니다. 감사합니다!');
  };

  const cartCount = cart.reduce((s, it) => s + it.qty, 0);

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="logo" onClick={() => { setInput(''); setQuery(''); setCategory(''); runSearch({ q: '', cat: '' }); }}>
            ⚡ Volt<span>Mall</span>
          </div>
          <form className="searchbar" onSubmit={submit}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="찾으시는 전자제품을 검색해 보세요 (예: 삼성 노트북, 무선 이어폰)"
            />
            <button type="submit">검색</button>
          </form>
          <div className="header-right">
            <label className={`ltr-switch ${useLtr ? 'on' : ''}`} title="LTR 재랭킹 (학습된 모델로 재정렬)">
              <input type="checkbox" checked={useLtr} onChange={toggleLtr} />
              <span>LTR {useLtr ? 'ON' : 'OFF'}</span>
            </label>
            <button className="cart-btn" onClick={() => setCartOpen(true)}>
              🛒 {cartCount > 0 && <b>{cartCount}</b>}
            </button>
          </div>
        </div>
        <div className="chips">
          {categories.map((c) => (
            <button key={c} className={`chip ${c === category ? 'active' : ''}`} onClick={() => selectCategory(c)}>
              {c}
            </button>
          ))}
        </div>
      </header>

      <main className="main">
        {!query && (
          <div className="hero">
            <h1>오늘의 추천 전자제품</h1>
            <p>인기 검색어
              {HOT_KEYWORDS.map((k) => (
                <button key={k} className="hot-kw" onClick={() => searchKeyword(k)}>{k}</button>
              ))}
            </p>
          </div>
        )}

        <div className="result-bar">
          <div>
            {query ? <>
              <strong>"{query}"</strong> 검색결과 {total.toLocaleString()}건
              {tookMs !== null && <span className="took"> · {tookMs}ms</span>}
              {ltrUsed && <span className="ltr-tag">LTR 적용</span>}
            </> : <strong>{category ? `${category} 인기상품` : '전체 인기상품'}</strong>}
          </div>
          <select value={sort} onChange={(e) => { setSort(e.target.value); runSearch({ srt: e.target.value }); }}>
            <option value="relevance">관련도순</option>
            <option value="popularity">인기순</option>
            <option value="price_asc">낮은가격순</option>
            <option value="price_desc">높은가격순</option>
            <option value="rating">평점순</option>
          </select>
        </div>

        {loading ? (
          <div className="loading">검색 중…</div>
        ) : (
          <div className="grid">
            {hits.map((p, i) => (
              <ProductCard
                key={p.id}
                product={p}
                position={p.position ?? i}
                onOpen={openProduct}
                onQuickCart={(prod) => addToCart(prod, { fromCard: true })}
              />
            ))}
            {hits.length === 0 && <div className="no-result">검색 결과가 없습니다 😢</div>}
          </div>
        )}
      </main>

      <ProductModal
        product={modal}
        onClose={() => setModal(null)}
        onAddCart={(p) => addToCart(p)}
        onBuyNow={buyNow}
      />
      <CartDrawer
        open={cartOpen}
        items={cart}
        onClose={() => setCartOpen(false)}
        onCheckout={checkout}
        onRemove={(id) => setCart((prev) => prev.filter((it) => it.product.id !== id))}
      />
      {cartOpen && <div className="drawer-back" onClick={() => setCartOpen(false)} />}
      <UbiDebugPanel ltrModel={ltrModel} />
      {toast && <div className="toast">{toast}</div>}

      <footer className="footer">
        VoltMall — OpenSearch UBI/LTR 데모 · 검색/클릭/장바구니/구매 행동이 OSI를 통해 실시간 수집됩니다
      </footer>
    </div>
  );
}
