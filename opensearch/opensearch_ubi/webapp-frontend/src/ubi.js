/**
 * UBI (User Behavior Insights) JavaScript Collector
 * Based on: https://docs.opensearch.org/latest/search-plugins/ubi/ubi-javascript-collector/
 */
import axios from 'axios';
import { getApiUrl } from './config';

const APPLICATION = 'ubi-sample-app';

/**
 * Get browser info from user agent
 */
function getBrowserInfo() {
  return navigator.userAgent;
}

// Get API base URL from runtime config
function getApiBase() {
  const apiUrl = getApiUrl();
  return apiUrl ? `${apiUrl}/api` : '/api';
}

// Generate UUID
function generateUUID() {
  try {
    return crypto.randomUUID();
  } catch {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
}

// Get or create client ID (persisted in localStorage)
function getClientId() {
  let clientId = localStorage.getItem('ubi_client_id');
  if (!clientId) {
    clientId = `CLIENT-${generateUUID()}`;
    localStorage.setItem('ubi_client_id', clientId);
  }
  return clientId;
}

// Get or create session ID (persisted in sessionStorage)
function getSessionId() {
  let sessionId = sessionStorage.getItem('ubi_session_id');
  if (!sessionId) {
    sessionId = `SESSION-${generateUUID()}`;
    sessionStorage.setItem('ubi_session_id', sessionId);
  }
  return sessionId;
}

// Store current query ID in session
function setQueryId(queryId) {
  sessionStorage.setItem('ubi_query_id', queryId);
}

function getQueryId() {
  return sessionStorage.getItem('ubi_query_id');
}

/**
 * UBI Event class
 */
export class UbiEvent {
  constructor(actionName, clientId, sessionId, queryId, eventAttributes, message) {
    this.action_name = actionName;
    this.client_id = clientId;
    this.session_id = sessionId;
    this.query_id = queryId;
    this.timestamp = Date.now();
    this.message = message;
    this.event_attributes = eventAttributes;
  }
}

/**
 * UBI Event Attributes
 */
export class UbiEventAttributes {
  constructor(objectType, objectId, description, objectDetail = null) {
    this.session_id = null;
    this.browser = null;
    this.dwell_time = null;
    this.result_count = null;
    this.position = null;
    this.object = {
      object_id_field: objectType,
      object_id: objectId,
      description: description,
      object_detail: objectDetail,
    };
  }
}

/**
 * UBI Event Object Detail
 */
export class UbiEventObjectDetail {
  constructor(price = null, margin = null, cost = null, supplier = null) {
    this.price = price;
    this.margin = margin;
    this.cost = cost;
    this.supplier = supplier;
  }
}

/**
 * UBI Query class
 */
export class UbiQuery {
  constructor(application, clientId, queryId, userQuery, objectIdField, queryAttributes = {}) {
    this.application = application;
    this.client_id = clientId;
    this.query_id = queryId;
    this.query_response_id = generateUUID();
    this.user_query = userQuery;
    this.object_id_field = objectIdField;
    this.query_attributes = queryAttributes;
    this.timestamp = new Date().toISOString();
    this.query_response_hit_ids = [];
  }
}

/**
 * UBI Client - Main interface for tracking
 */
export class UbiClient {
  constructor(apiBase = null) {
    this.apiBase = apiBase || getApiBase();
    this.clientId = getClientId();
    this.sessionId = getSessionId();
    this.eventQueue = [];
    this.flushInterval = null;
    this.pageEnterTime = Date.now();
    this.lastQueryTime = null;
    this.eventListeners = [];

    // Start periodic flush
    this.startPeriodicFlush();

    // Flush on page unload
    window.addEventListener('beforeunload', () => this.flush());
  }

  /**
   * Subscribe to event notifications
   */
  onEvent(callback) {
    this.eventListeners.push(callback);
    return () => {
      this.eventListeners = this.eventListeners.filter((cb) => cb !== callback);
    };
  }

  /**
   * Notify all listeners of an event
   */
  notifyListeners(eventType, description) {
    this.eventListeners.forEach((cb) => cb({ type: eventType, description }));
  }

  /**
   * Calculate dwell time in seconds
   */
  calculateDwellTime() {
    const baseTime = this.lastQueryTime || this.pageEnterTime;
    return (Date.now() - baseTime) / 1000;
  }

  startPeriodicFlush() {
    this.flushInterval = setInterval(() => this.flush(), 5000);
  }

  /**
   * Log a search query
   */
  async trackQuery(userQuery, hitIds = [], resultCount = null) {
    this.lastQueryTime = Date.now();
    const queryId = generateUUID();
    setQueryId(queryId);

    const query = new UbiQuery(
      APPLICATION,
      this.clientId,
      queryId,
      userQuery,
      '_id',
      {}
    );
    query.query_response_hit_ids = hitIds;
    query.session_id = this.sessionId;

    try {
      await axios.post(`${this.apiBase}/ubi/queries`, [query]);
      console.log('[UBI] Query tracked:', queryId);

      // Track on_search event with result_count
      const searchEvent = new UbiEvent(
        'on_search',
        this.clientId,
        this.sessionId,
        queryId,
        new UbiEventAttributes('query', queryId, userQuery),
        `Search: ${userQuery}`
      );
      searchEvent.event_attributes.result_count = resultCount ?? hitIds.length;
      searchEvent.event_attributes.session_id = this.sessionId;
      searchEvent.event_attributes.browser = getBrowserInfo();
      searchEvent.event_attributes.dwell_time = this.calculateDwellTime();
      this.trackEvent(searchEvent);
    } catch (err) {
      console.error('[UBI] Failed to track query:', err);
    }

    return queryId;
  }

  /**
   * Track a generic event
   */
  trackEvent(event) {
    this.eventQueue.push(event);
    console.log('[UBI] Event queued:', event.action_name);
    this.notifyListeners(event.action_name, event.message);
  }

  /**
   * Track a click event with full product details
   */
  trackClick(objectId, position, description = '', product = null) {
    const queryId = getQueryId();
    let objectDetail = null;
    if (product) {
      objectDetail = new UbiEventObjectDetail(
        product.price,
        product.margin,
        product.cost,
        product.supplier
      );
    }
    const event = new UbiEvent(
      'click',
      this.clientId,
      this.sessionId,
      queryId,
      new UbiEventAttributes('product', objectId, description, objectDetail),
      `Clicked on ${objectId} at position ${position}`
    );
    event.event_attributes.position = { ordinal: position };
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Track product view with full product details
   */
  trackView(objectId, description = '', product = null) {
    const queryId = getQueryId();
    let objectDetail = null;
    if (product) {
      objectDetail = new UbiEventObjectDetail(
        product.price,
        product.margin,
        product.cost,
        product.supplier
      );
    }
    const event = new UbiEvent(
      'view',
      this.clientId,
      this.sessionId,
      queryId,
      new UbiEventAttributes('product', objectId, description, objectDetail),
      `Viewed ${objectId}`
    );
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Track add to cart with full product details
   */
  trackAddToCart(objectId, quantity = 1, description = '', product = null) {
    const queryId = getQueryId();
    let objectDetail = null;
    if (product) {
      objectDetail = new UbiEventObjectDetail(
        product.price,
        product.margin,
        product.cost,
        product.supplier
      );
    }
    const event = new UbiEvent(
      'add_to_cart',
      this.clientId,
      this.sessionId,
      queryId,
      new UbiEventAttributes('product', objectId, description, objectDetail),
      `Added ${quantity} of ${objectId} to cart`
    );
    event.event_attributes.quantity = quantity;
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Track search event
   */
  trackSearch(userQuery, resultCount) {
    const queryId = getQueryId();
    const event = new UbiEvent(
      'search',
      this.clientId,
      this.sessionId,
      queryId,
      new UbiEventAttributes('query', queryId, userQuery),
      `Search: ${userQuery}`
    );
    event.event_attributes.result_count = resultCount;
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Track impression (results shown)
   */
  trackImpression(objectIds) {
    const queryId = getQueryId();
    const event = new UbiEvent(
      'impression',
      this.clientId,
      this.sessionId,
      queryId,
      { object_ids: objectIds, result_count: objectIds.length },
      `Displayed ${objectIds.length} results`
    );
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Track hover event with full product details
   */
  trackHover(objectId, description = '', product = null) {
    const queryId = getQueryId();
    let objectDetail = null;
    if (product) {
      objectDetail = new UbiEventObjectDetail(
        product.price,
        product.margin,
        product.cost,
        product.supplier
      );
    }
    const event = new UbiEvent(
      'product_hover',
      this.clientId,
      this.sessionId,
      queryId,
      new UbiEventAttributes('product', objectId, description, objectDetail),
      `Hovered on ${objectId}`
    );
    event.event_attributes.session_id = this.sessionId;
    event.event_attributes.browser = getBrowserInfo();
    event.event_attributes.dwell_time = this.calculateDwellTime();
    this.trackEvent(event);
  }

  /**
   * Flush queued events to server
   */
  async flush() {
    if (this.eventQueue.length === 0) return;

    const events = [...this.eventQueue];
    this.eventQueue = [];

    try {
      await axios.post(`${this.apiBase}/ubi/events`, events);
      console.log(`[UBI] Flushed ${events.length} events`);
    } catch (err) {
      console.error('[UBI] Failed to flush events:', err);
      // Re-queue failed events
      this.eventQueue = [...events, ...this.eventQueue];
    }
  }

  /**
   * Get current tracking info
   */
  getTrackingInfo() {
    return {
      clientId: this.clientId,
      sessionId: this.sessionId,
      queryId: getQueryId(),
      queuedEvents: this.eventQueue.length,
    };
  }

  destroy() {
    if (this.flushInterval) {
      clearInterval(this.flushInterval);
    }
    this.flush();
  }
}

// Singleton instance
let ubiClientInstance = null;

export function getUbiClient() {
  if (!ubiClientInstance) {
    ubiClientInstance = new UbiClient();
  }
  return ubiClientInstance;
}

export default {
  UbiClient,
  UbiEvent,
  UbiEventAttributes,
  UbiEventObjectDetail,
  UbiQuery,
  getUbiClient,
};
