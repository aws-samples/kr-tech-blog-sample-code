import React from "react";
import ReactDOM from "react-dom/client";
import "@cloudscape-design/global-styles/index.css";
import { App } from "./App";

// Capture OAuth tokens from URL hash BEFORE React renders.
// Cognito implicit flow returns: #id_token=xxx&access_token=xxx&token_type=Bearer&expires_in=3600
const hash = window.location.hash.substring(1);
if (hash && hash.includes("id_token")) {
  const params = new URLSearchParams(hash);
  const idToken = params.get("id_token");
  const accessToken = params.get("access_token");
  if (idToken && accessToken) {
    sessionStorage.setItem("av30_id_token", idToken);
    sessionStorage.setItem("av30_access_token", accessToken);
    // Remove hash from URL to prevent re-processing
    window.history.replaceState(null, "", window.location.pathname);
  }
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element not found");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
