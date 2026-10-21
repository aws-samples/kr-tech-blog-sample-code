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
 * The user dashboard authenticates from the `userId` + `token` query params,
 * so this link lets a participant re-enter the dashboard at any time and mint
 * a fresh (5-min) workspace URL on demand — unlike the raw workspace URL,
 * which expires almost immediately.
 */
export function participantLink(userId: string, token: string): string {
  const base = getConfig().userDashboardUrl.replace(/\/+$/, "");
  return `${base}/?userId=${encodeURIComponent(userId)}&token=${encodeURIComponent(token)}`;
}
