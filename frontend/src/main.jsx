import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { PublicClientApplication, EventType } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { ThemeProvider } from './ThemeContext'
import { msalConfig } from './authConfig'
import { currentEnvironment } from './enviroments/env.js'
import './index.css'
import App from './App.jsx'

/**
 * MSAL instance — only created for Azure/cloud environments.
 * Local dev skips MSAL entirely (no login required).
 */
let msalInstance = null;
const needsAuth = currentEnvironment === 'azure';

if (needsAuth) {
  msalInstance = new PublicClientApplication(msalConfig);

  // Handle redirect response on page load
  msalInstance.initialize().then(() => {
    // Set the first account as active if one exists
    const accounts = msalInstance.getAllAccounts();
    if (accounts.length > 0) {
      msalInstance.setActiveAccount(accounts[0]);
    }

    // Listen for login events to set active account
    msalInstance.addEventCallback((event) => {
      if (
        event.eventType === EventType.LOGIN_SUCCESS &&
        event.payload?.account
      ) {
        msalInstance.setActiveAccount(event.payload.account);
      }
    });
  });
}

/**
 * Render tree:
 * - Azure: MsalProvider wraps the app for SSO
 * - Local/Other: No MsalProvider needed
 */
function Root() {
  const app = (
    <ThemeProvider>
      <App />
    </ThemeProvider>
  );

  if (needsAuth && msalInstance) {
    return (
      <MsalProvider instance={msalInstance}>
        {app}
      </MsalProvider>
    );
  }

  return app;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

export { msalInstance };
