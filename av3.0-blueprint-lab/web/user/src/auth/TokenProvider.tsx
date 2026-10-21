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

interface TokenAuthProviderProps {
  children: ReactNode;
}

export function TokenAuthProvider({ children }: TokenAuthProviderProps): React.JSX.Element {
  const [userId, setUserId] = useState<string | null>(null);
  const [participantToken, setParticipantToken] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const uid = params.get("userId");
    const token = params.get("token");

    if (uid) {
      setUserId(uid);
    }
    if (token) {
      setParticipantToken(token);
    }
  }, []);

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
