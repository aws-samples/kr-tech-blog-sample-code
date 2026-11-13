import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";
import { getConfig } from "../config";

/**
 * Cognito hosted-UI auth using the AUTHORIZATION CODE flow with PKCE.
 *
 * This replaced the implicit flow (`response_type=token`). Three reasons:
 *
 *  1. infra/av30_constructs/auth.py has always declared
 *     `authorization_code_grant=True, implicit_code_grant=False`. The implicit flow
 *     worked only because the live user-pool client had been edited BY HAND, so a
 *     `cdk deploy` into a fresh account produced a client that rejects the flow this
 *     file used — admin sign-in was impossible from the code alone.
 *  2. Implicit returns the access token in the URL fragment, where it reaches browser
 *     history, extensions and (historically) Referer headers. OAuth 2.0 Security BCP
 *     advises against it and OAuth 2.1 removes it. The client has no secret, so PKCE
 *     is the correct SPA flow.
 *  3. Implicit issues no refresh token. The old code admitted this — "if token expires
 *     while tab is open, force re-login" — so an admin was thrown out mid-session when
 *     the id token expired. The code flow returns a refresh token and this file now
 *     refreshes silently.
 *
 * Token storage stays in sessionStorage: it is cleared when the tab closes, and it is
 * not shared across tabs/origins. The refresh token lives there too, which is the
 * accepted trade-off for a browser app with no backend session — its blast radius is
 * this origin and this tab only.
 */

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  idToken: string | null;
  accessToken: string | null;
  userEmail: string | null;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  login: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const KEY_ID = "av30_id_token";
const KEY_ACCESS = "av30_access_token";
const KEY_REFRESH = "av30_refresh_token";
const KEY_VERIFIER = "av30_pkce_verifier";
const KEY_STATE = "av30_oauth_state";

function parseJwt(token: string): Record<string, unknown> {
  const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  const json = decodeURIComponent(
    atob(base64)
      .split("")
      .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
      .join("")
  );
  return JSON.parse(json);
}

function isTokenExpired(token: string): boolean {
  try {
    return Date.now() >= (parseJwt(token).exp as number) * 1000;
  } catch {
    return true;
  }
}

/** base64url of raw bytes — no padding, URL-safe alphabet (RFC 7636 §A). */
function base64UrlEncode(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomUrlSafe(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

/** S256 challenge. Cognito supports S256; "plain" is not used. */
async function sha256Challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier)
  );
  return base64UrlEncode(new Uint8Array(digest));
}

interface TokenResponse {
  id_token?: string;
  access_token?: string;
  refresh_token?: string;
  error?: string;
  error_description?: string;
}

async function postToken(body: Record<string, string>): Promise<TokenResponse> {
  const config = getConfig();
  const res = await fetch(`${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body).toString(),
  });
  // Cognito returns 400 with a JSON error body; surface that rather than a bare status.
  const data = (await res.json().catch(() => ({}))) as TokenResponse;
  if (!res.ok || data.error) {
    throw new Error(
      data.error_description ?? data.error ?? `Token endpoint returned ${res.status}`
    );
  }
  return data;
}

export function CognitoAuthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    idToken: null,
    accessToken: null,
    userEmail: null,
    error: null,
  });

  // Guards the one-shot code exchange. React 18 StrictMode mounts effects twice in
  // dev, and an authorization code is single-use — the second exchange would fail
  // with invalid_grant and log the admin straight back out.
  const exchangedRef = useRef(false);

  const applyTokens = useCallback((t: TokenResponse) => {
    if (!t.id_token || !t.access_token) {
      throw new Error("Token response did not include id_token/access_token");
    }
    sessionStorage.setItem(KEY_ID, t.id_token);
    sessionStorage.setItem(KEY_ACCESS, t.access_token);
    // Cognito omits refresh_token on a refresh_token grant — keep the existing one.
    if (t.refresh_token) sessionStorage.setItem(KEY_REFRESH, t.refresh_token);
    setState({
      isAuthenticated: true,
      isLoading: false,
      idToken: t.id_token,
      accessToken: t.access_token,
      userEmail: (parseJwt(t.id_token).email as string) ?? null,
      error: null,
    });
  }, []);

  const clearSession = useCallback((error: string | null) => {
    [KEY_ID, KEY_ACCESS, KEY_REFRESH, KEY_VERIFIER, KEY_STATE].forEach((k) =>
      sessionStorage.removeItem(k)
    );
    setState({
      isAuthenticated: false,
      isLoading: false,
      idToken: null,
      accessToken: null,
      userEmail: null,
      error,
    });
  }, []);

  const login = useCallback(async () => {
    const config = getConfig();
    const verifier = randomUrlSafe(64);
    const oauthState = randomUrlSafe(16);
    sessionStorage.setItem(KEY_VERIFIER, verifier);
    sessionStorage.setItem(KEY_STATE, oauthState);
    const params = new URLSearchParams({
      response_type: "code",
      client_id: config.cognitoClientId,
      redirect_uri: config.cognitoRedirectUri,
      scope: "openid email profile",
      code_challenge_method: "S256",
      code_challenge: await sha256Challenge(verifier),
      state: oauthState,
    });
    window.location.href = `${config.cognitoDomain}/oauth2/authorize?${params.toString()}`;
  }, []);

  useEffect(() => {
    const config = getConfig();
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const returnedState = url.searchParams.get("state");
    const oauthError =
      url.searchParams.get("error_description") ?? url.searchParams.get("error");

    const stripQuery = () =>
      window.history.replaceState(null, "", window.location.pathname);

    if (oauthError) {
      stripQuery();
      clearSession(oauthError);
      return;
    }

    if (code) {
      if (exchangedRef.current) return;
      exchangedRef.current = true;

      const verifier = sessionStorage.getItem(KEY_VERIFIER);
      const expectedState = sessionStorage.getItem(KEY_STATE);
      stripQuery();

      // CSRF check: the state we generated must come back unchanged.
      if (!expectedState || returnedState !== expectedState) {
        clearSession("Sign-in state mismatch — please try again.");
        return;
      }
      if (!verifier) {
        clearSession("Sign-in verifier missing — please try again.");
        return;
      }

      postToken({
        grant_type: "authorization_code",
        client_id: config.cognitoClientId,
        code,
        redirect_uri: config.cognitoRedirectUri,
        code_verifier: verifier,
      })
        .then((t) => {
          sessionStorage.removeItem(KEY_VERIFIER);
          sessionStorage.removeItem(KEY_STATE);
          applyTokens(t);
        })
        .catch((e: Error) => clearSession(e.message));
      return;
    }

    // No code in the URL — resume an existing session if it is still valid.
    const storedId = sessionStorage.getItem(KEY_ID);
    const storedAccess = sessionStorage.getItem(KEY_ACCESS);
    if (storedId && storedAccess && !isTokenExpired(storedId)) {
      setState({
        isAuthenticated: true,
        isLoading: false,
        idToken: storedId,
        accessToken: storedAccess,
        userEmail: (parseJwt(storedId).email as string) ?? null,
        error: null,
      });
      return;
    }

    // Expired id token but a refresh token on hand: renew instead of bouncing the
    // admin to the login page. This is what the implicit flow could not do.
    const storedRefresh = sessionStorage.getItem(KEY_REFRESH);
    if (storedRefresh) {
      postToken({
        grant_type: "refresh_token",
        client_id: config.cognitoClientId,
        refresh_token: storedRefresh,
      })
        .then(applyTokens)
        .catch(() => clearSession(null));
      return;
    }

    setState((prev) => ({ ...prev, isLoading: false }));
  }, [applyTokens, clearSession]);

  // Renew shortly before the id token expires, so a long admin session does not drop.
  useEffect(() => {
    if (!state.idToken) return;
    const exp = (parseJwt(state.idToken).exp as number) * 1000;
    const msUntil = exp - Date.now() - 120_000; // 2 min of headroom
    const refresh = () => {
      const storedRefresh = sessionStorage.getItem(KEY_REFRESH);
      if (!storedRefresh) {
        clearSession("Session expired. Please log in again.");
        return;
      }
      postToken({
        grant_type: "refresh_token",
        client_id: getConfig().cognitoClientId,
        refresh_token: storedRefresh,
      })
        .then(applyTokens)
        .catch(() => clearSession("Session expired. Please log in again."));
    };
    if (msUntil <= 0) {
      refresh();
      return;
    }
    const timer = setTimeout(refresh, msUntil);
    return () => clearTimeout(timer);
  }, [state.idToken, applyTokens, clearSession]);

  const logout = useCallback(() => {
    const config = getConfig();
    clearSession(null);
    const params = new URLSearchParams({
      client_id: config.cognitoClientId,
      logout_uri: config.cognitoRedirectUri,
    });
    window.location.href = `${config.cognitoDomain}/logout?${params.toString()}`;
  }, [clearSession]);

  const contextValue = useMemo(
    () => ({
      ...state,
      // login is async (it awaits the PKCE challenge digest); the context exposes the
      // plain void signature every caller already uses.
      login: () => {
        void login();
      },
      logout,
    }),
    [state, login, logout]
  );

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within CognitoAuthProvider");
  }
  return ctx;
}
