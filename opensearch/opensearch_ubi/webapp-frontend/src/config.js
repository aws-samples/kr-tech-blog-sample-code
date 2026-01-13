/**
 * Runtime Configuration Loader
 *
 * Loads configuration from /config.json at runtime.
 * This allows the API URL to be set during CDK deployment
 * without requiring a frontend rebuild.
 */

let configPromise = null;
let cachedConfig = null;

/**
 * Default configuration (used during development)
 */
const defaultConfig = {
  apiUrl: '',  // Empty string means use relative path (for dev proxy)
};

/**
 * Load configuration from /config.json
 * Falls back to environment variable or default config if not available.
 */
export async function loadConfig() {
  if (cachedConfig) {
    return cachedConfig;
  }

  if (!configPromise) {
    configPromise = (async () => {
      try {
        const response = await fetch('/config.json');
        if (response.ok) {
          const config = await response.json();
          console.log('[Config] Loaded from /config.json:', config);
          cachedConfig = config;
          return config;
        }
      } catch (err) {
        console.log('[Config] /config.json not found, using defaults');
      }

      // Fallback to environment variable (for local development)
      const envApiUrl = import.meta.env.VITE_API_URL || '';
      cachedConfig = {
        ...defaultConfig,
        apiUrl: envApiUrl,
      };
      console.log('[Config] Using fallback config:', cachedConfig);
      return cachedConfig;
    })();
  }

  return configPromise;
}

/**
 * Get cached config synchronously (returns null if not loaded yet)
 */
export function getConfig() {
  return cachedConfig;
}

/**
 * Get API URL (must call loadConfig first)
 */
export function getApiUrl() {
  return cachedConfig?.apiUrl || '';
}

export default { loadConfig, getConfig, getApiUrl };
