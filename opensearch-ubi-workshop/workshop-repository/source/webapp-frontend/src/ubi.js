/**
 * UBI (User Behavior Insights) collector for VoltMall.
 *
 * Events are queued and flushed in batches to POST /api/ubi/events; the
 * backend signs and forwards them to the OpenSearch Ingestion (OSI) pipeline.
 * The UBI *query* record is written server-side by /api/search — the client
 * only keeps the returned query_id and attaches it to subsequent events.
 */
const APPLICATION = 'voltmall';
const FLUSH_INTERVAL_MS = 4000;
const FLUSH_THRESHOLD = 10;

function uuid() {
  try {
    return crypto.randomUUID();
  } catch {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }
}

function persistent(storage, key, prefix) {
  let v = storage.getItem(key);
  if (!v) {
    v = `${prefix}-${uuid()}`;
    storage.setItem(key, v);
  }
  return v;
}

class UbiClient {
  constructor() {
    this.clientId = persistent(localStorage, 'ubi_client_id', 'CLIENT');
    this.sessionId = persistent(sessionStorage, 'ubi_session_id', 'SESSION');
    this.queryId = sessionStorage.getItem('ubi_query_id') || null;
    this.queue = [];
    this.listeners = [];
    this.lastQueryTime = Date.now();
    this.timer = setInterval(() => this.flush(), FLUSH_INTERVAL_MS);
    window.addEventListener('beforeunload', () => this.flush(true));
  }

  onEvent(cb) {
    this.listeners.push(cb);
    return () => (this.listeners = this.listeners.filter((f) => f !== cb));
  }

  setQueryId(queryId) {
    this.queryId = queryId;
    this.lastQueryTime = Date.now();
    sessionStorage.setItem('ubi_query_id', queryId || '');
  }

  dwell() {
    return Math.round((Date.now() - this.lastQueryTime) / 100) / 10;
  }

  track(actionName, { objectId = null, position = null, product = null, message = '', extra = {} } = {}) {
    const event = {
      application: APPLICATION,
      action_name: actionName,
      query_id: this.queryId,
      client_id: this.clientId,
      session_id: this.sessionId,
      timestamp: Date.now(),
      message,
      event_attributes: {
        session_id: this.sessionId,
        dwell_time: this.dwell(),
        browser: navigator.userAgent,
        ...(position !== null ? { position: { ordinal: position } } : {}),
        ...(objectId
          ? {
              object: {
                object_id: objectId,
                object_id_field: 'product_id',
                name: product?.name || null,
                object_detail: product
                  ? { price: product.price, brand: product.brand, category: product.category }
                  : null,
              },
            }
          : {}),
        ...extra,
      },
    };
    this.queue.push(event);
    this.listeners.forEach((cb) => cb(event));
    if (this.queue.length >= FLUSH_THRESHOLD) this.flush();
  }

  trackImpression(objectIds) {
    this.track('impression', {
      message: `${objectIds.length}개 결과 노출`,
      extra: { result_count: objectIds.length },
    });
  }

  trackClick(objectId, position, product) {
    this.track('click', {
      objectId,
      position,
      product,
      message: `${position}번 위치 ${objectId} 클릭`,
    });
  }

  trackView(objectId, product) {
    this.track('view', { objectId, product, message: `${objectId} 상세 조회` });
  }

  trackAddToCart(objectId, quantity, product) {
    this.track('add_to_cart', {
      objectId,
      product,
      message: `${objectId} 장바구니 담기 x${quantity}`,
      extra: { quantity },
    });
  }

  trackPurchase(objectId, quantity, product) {
    this.track('purchase', {
      objectId,
      product,
      message: `${objectId} 구매 x${quantity}`,
      extra: { quantity },
    });
  }

  async flush(sync = false) {
    if (!this.queue.length) return;
    const events = this.queue.splice(0, this.queue.length);
    try {
      await fetch('/api/ubi/events', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(events),
        keepalive: sync,
      });
    } catch (e) {
      // re-queue on failure
      this.queue.unshift(...events);
    }
  }
}

let instance = null;
export function getUbi() {
  if (!instance) instance = new UbiClient();
  return instance;
}
