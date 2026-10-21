import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AppLayout,
  BreadcrumbGroup,
  Flashbar,
  FlashbarProps,
  Header,
  SideNavigation,
  Tabs,
} from "@cloudscape-design/components";
import { CognitoAuthProvider, useAuth } from "./auth/CognitoProvider";
import { loadConfig } from "./config";
import { UsersPage } from "./pages/UsersPage";
import { SessionsPage } from "./pages/SessionsPage";
import { CostsPage } from "./pages/CostsPage";

type FlashItem = FlashbarProps.MessageDefinition;

interface FlashContextValue {
  addFlash: (item: FlashItem) => void;
}

export const FlashContext = React.createContext<FlashContextValue>({
  addFlash: () => {},
});

function AppShell() {
  const { isAuthenticated, isLoading, login, logout, userEmail, error } =
    useAuth();
  const [activeTab, setActiveTab] = useState("users");
  const [flashItems, setFlashItems] = useState<FlashItem[]>([]);
  // Monotonic counter for unique flash ids. Date.now() collides when several
  // flashes are added in the same millisecond (e.g. an error burst), which
  // would make onDismiss remove the wrong item.
  const flashCounter = useRef(0);

  // MUST be memoized. Pages take addFlash as a dependency of their data-fetch
  // useCallback; if addFlash changed identity every render, the fetch callback
  // would too, its useEffect would re-fire, and on an API error the resulting
  // addFlash -> re-render -> new addFlash -> re-fetch cycle spins infinitely
  // (hundreds of calls/sec) and blanks the app. Stable identity breaks the loop.
  const addFlash = useCallback((item: FlashItem) => {
    const id = `flash-${(flashCounter.current += 1)}`;
    const flashItem: FlashItem = {
      ...item,
      id,
      dismissible: true,
      onDismiss: () => {
        setFlashItems((prev) => prev.filter((f) => f.id !== id));
      },
    };
    setFlashItems((prev) => [...prev, flashItem]);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      setFlashItems((prev) => prev.filter((f) => f.id !== id));
    }, 5000);
  }, []);

  if (isLoading) {
    return (
      <AppLayout
        navigationHide
        toolsHide
        content={
          <div style={{ padding: "40px", textAlign: "center" }}>
            Loading...
          </div>
        }
      />
    );
  }

  if (!isAuthenticated) {
    return (
      <AppLayout
        navigationHide
        toolsHide
        content={
          <div style={{ padding: "40px", textAlign: "center" }}>
            <Header variant="h1">AV 3.0 Admin Dashboard</Header>
            <p style={{ marginTop: "16px" }}>
              {error ?? "Please sign in to continue."}
            </p>
            <button
              onClick={login}
              style={{
                marginTop: "16px",
                padding: "10px 24px",
                fontSize: "16px",
                cursor: "pointer",
                backgroundColor: "#0972d3",
                color: "#fff",
                border: "none",
                borderRadius: "4px",
              }}
            >
              Sign In with Cognito
            </button>
          </div>
        }
      />
    );
  }

  return (
    // addFlash has a stable identity (useCallback above), so a fresh { addFlash }
    // object here does not cause consumers to re-fetch. Do NOT wrap this in a
    // hook (useMemo): it sits after the early returns for isLoading/!isAuthenticated,
    // and a conditionally-called hook throws React #310 ("more hooks than previous
    // render") the moment auth state flips — which blanks the whole app.
    <FlashContext.Provider value={{ addFlash }}>
      <AppLayout
        headerSelector="#app-header"
        navigation={
          <SideNavigation
            header={{ text: "AV 3.0 Admin", href: "/" }}
            items={[
              { type: "link", text: "Dashboard", href: "/" },
              { type: "divider" },
              {
                type: "link",
                text: `${userEmail ?? "User"}`,
                href: "#",
              },
              {
                type: "link",
                text: "Sign Out",
                href: "#",
                info: undefined,
              },
            ]}
            onFollow={(event) => {
              event.preventDefault();
              if (event.detail.text === "Sign Out") {
                logout();
              }
            }}
          />
        }
        breadcrumbs={
          <BreadcrumbGroup
            items={[
              { text: "AV 3.0", href: "/" },
              { text: "Admin", href: "/" },
            ]}
          />
        }
        notifications={<Flashbar items={flashItems} />}
        toolsHide
        content={
          <div>
            <Header variant="h1" description="Manage users, sessions, and costs">
              AV 3.0 Blueprint Lab
            </Header>
            <Tabs
              activeTabId={activeTab}
              onChange={({ detail }) => setActiveTab(detail.activeTabId)}
              tabs={[
                {
                  id: "users",
                  label: "Users",
                  content: <UsersPage />,
                },
                {
                  id: "sessions",
                  label: "Sessions",
                  content: <SessionsPage />,
                },
                {
                  id: "costs",
                  label: "Costs",
                  content: <CostsPage />,
                },
              ]}
            />
          </div>
        }
      />
    </FlashContext.Provider>
  );
}

export function App() {
  const [configLoaded, setConfigLoaded] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    loadConfig()
      .then(() => setConfigLoaded(true))
      .catch((err: Error) => setConfigError(err.message));
  }, []);

  if (configError) {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#d91515" }}>
        <h2>Configuration Error</h2>
        <p>{configError}</p>
        <p>Ensure /config.json is available.</p>
      </div>
    );
  }

  if (!configLoaded) {
    return (
      <div style={{ padding: "40px", textAlign: "center" }}>
        Initializing...
      </div>
    );
  }

  return (
    <CognitoAuthProvider>
      <AppShell />
    </CognitoAuthProvider>
  );
}
