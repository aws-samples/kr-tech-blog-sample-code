export interface AppConfig {
  apiBaseUrl: string;
  cognitoPoolId: string;
  cognitoClientId: string;
  cognitoDomain: string;
  cognitoRedirectUri: string;
  region: string;
  // Base URL of the participant (user) dashboard, e.g.
  // https://<user-cloudfront-domain> — used to build durable, non-expiring
  // links to hand out to workshop participants.
  userDashboardUrl: string;
}

let cachedConfig: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (cachedConfig) {
    return cachedConfig;
  }

  const response = await fetch("/config.json");
  if (!response.ok) {
    throw new Error(`Failed to load config: ${response.status}`);
  }

  cachedConfig = (await response.json()) as AppConfig;
  return cachedConfig;
}

export function getConfig(): AppConfig {
  if (!cachedConfig) {
    throw new Error("Config not loaded. Call loadConfig() first.");
  }
  return cachedConfig;
}

/**
 * Build the durable participant dashboard link for a provisioned user.
 * The user dashboard authenticates from `userId` + `token`, so this link lets a
 * participant re-enter the dashboard at any time and mint a fresh (5-min)
 * workspace URL on demand — unlike the raw workspace URL, which expires almost
 * immediately.
 *
 * The link is a bearer credential: whoever holds it acts as that participant
 * until the user is deleted. The pair goes in the URL fragment, which the
 * browser never sends to the server (no CDN log, no Referer); the dashboard
 * then moves it to sessionStorage and removes it from the address bar. Older
 * `?userId=&token=` links are still accepted.
 */
export function participantLink(userId: string, token: string): string {
  const base = getConfig().userDashboardUrl.replace(/\/+$/, "");
  return `${base}/#userId=${encodeURIComponent(userId)}&token=${encodeURIComponent(token)}`;
}
