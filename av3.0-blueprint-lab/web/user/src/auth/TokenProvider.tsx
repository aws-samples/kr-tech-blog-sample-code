import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { getConfig } from "../config";
import { ApiClient } from "../api/client";

interface TokenAuthContextValue {
  userId: string | null;
  participantToken: string | null;
  setParticipantToken: (token: string) => void;
  isAuthenticated: boolean;
  apiClient: ApiClient | null;
}

const TokenAuthContext = createContext<TokenAuthContextValue>({
  userId: null,
  participantToken: null,
  setParticipantToken: () => {},
  isAuthenticated: false,
  apiClient: null,
});

export function useTokenAuth(): TokenAuthContextValue {
  return useContext(TokenAuthContext);
}

interface ParticipantCredentials {
  userId: string | null;
  token: string | null;
}

// The participant link is a bearer credential: whoever holds it can act as this
// participant until the user is deleted. The admin dashboard hands it out as
// /#userId=...&token=... because a fragment is never sent to the server, so it
// stays out of CDN logs and the Referer header. Links handed out earlier as
// /?userId=...&token=... still work.
//
// On load the pair moves into sessionStorage and leaves the address bar, so it
// does not end up in a screen share, a copied URL or a bookmark of the open
// page. sessionStorage is per tab and survives a reload, which is what keeps
// the participant signed in across F5. A new tab or a bookmark of the stripped
// page starts in Demo Mode; the participant reopens the original link.
const STORAGE_KEY = "av30.participant";
const URL_KEYS = ["userId", "token"] as const;

function pairFrom(params: URLSearchParams): ParticipantCredentials | null {
  const userId = params.get("userId");
  const token = params.get("token");
  return userId && token ? { userId, token } : null;
}

function readStored(): ParticipantCredentials | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { userId, token } = parsed as Record<string, unknown>;
    return typeof userId === "string" && userId && typeof token === "string" && token
      ? { userId, token }
      : null;
  } catch {
    // Storage disabled or the value is not ours: behave as if nothing is stored.
    return null;
  }
}

function writeStored(creds: ParticipantCredentials): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(creds));
  } catch {
    // Storage disabled: this page load still works, a reload drops to Demo Mode.
  }
}

// Remove userId/token from both the query and the fragment, keeping anything
// else in the URL. Runs even when only half a pair is present, so a stray token
// never stays in the address bar. A part without our keys is left untouched
// (re-serialising would turn a plain "#section" into "#section=").
function stripFromUrl(): void {
  const url = new URL(window.location.href);
  const hash = new URLSearchParams(url.hash.slice(1));
  let changed = false;
  for (const key of URL_KEYS) {
    if (url.searchParams.has(key)) {
      url.searchParams.delete(key);
      changed = true;
    }
  }
  if (URL_KEYS.some((key) => hash.has(key))) {
    for (const key of URL_KEYS) hash.delete(key);
    const rest = hash.toString();
    url.hash = rest ? `#${rest}` : "";
    changed = true;
  }
  if (changed) {
    window.history.replaceState(window.history.state, "", url.href);
  }
}

// A complete pair in the URL, fragment first, then the legacy query. When one is
// found it replaces whatever is stored: the URL is the newer intent.
function takeFromUrl(): ParticipantCredentials | null {
  const fromUrl =
    pairFrom(new URLSearchParams(window.location.hash.slice(1))) ??
    pairFrom(new URLSearchParams(window.location.search));
  stripFromUrl();
  if (fromUrl) writeStored(fromUrl);
  return fromUrl;
}

// Synchronous, so the first render already knows whether it is authenticated
// (no Demo Mode flash). Safe to run twice under StrictMode: the second call
// finds the URL already stripped and reads the same pair back from storage.
function loadCredentials(): ParticipantCredentials {
  return takeFromUrl() ?? readStored() ?? { userId: null, token: null };
}

interface TokenAuthProviderProps {
  children: ReactNode;
}

export function TokenAuthProvider({ children }: TokenAuthProviderProps): React.JSX.Element {
  const [creds, setCreds] = useState<ParticipantCredentials>(loadCredentials);
  const { userId, token: participantToken } = creds;

  // Pasting a #userId=...&token=... link into a tab that already shows the
  // dashboard is a same-document navigation: no reload, so the initializer
  // above never sees it. Pick it up here, or the token would sit in the
  // address bar and the page would keep showing the previous participant.
  useEffect(() => {
    const onHashChange = () => {
      const next = takeFromUrl();
      if (next) setCreds(next);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setParticipantToken = (token: string) => setCreds((prev) => ({ ...prev, token }));

  const isAuthenticated = userId !== null && participantToken !== null;

  // Build an ApiClient once the participant token is known. Safe to call
  // getConfig() here because App gates render until loadConfig() resolves.
  const apiClient = useMemo(
    () => (participantToken ? new ApiClient(getConfig().apiBaseUrl, participantToken) : null),
    [participantToken]
  );

  return (
    <TokenAuthContext.Provider
      value={{ userId, participantToken, setParticipantToken, isAuthenticated, apiClient }}
    >
      {children}
    </TokenAuthContext.Provider>
  );
}
