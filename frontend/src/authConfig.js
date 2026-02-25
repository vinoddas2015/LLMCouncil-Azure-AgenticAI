/**
 * MSAL (Microsoft Authentication Library) configuration for Entra ID SSO.
 *
 * App Registration: llmcouncil-agents
 * Client ID: a73fe3b0-6f94-4093-ba33-441d25772636
 * Tenant: Bayer (fcb2b37b-5da0-466b-9b83-0014b67a7c78)
 * API Scope: api://a73fe3b0-6f94-4093-ba33-441d25772636/user_impersonation
 */

import { LogLevel } from '@azure/msal-browser';

const CLIENT_ID = 'a73fe3b0-6f94-4093-ba33-441d25772636';
const TENANT_ID = 'fcb2b37b-5da0-466b-9b83-0014b67a7c78';

/**
 * MSAL configuration object.
 * @see https://github.com/AzureAD/microsoft-authentication-library-for-js/blob/dev/lib/msal-browser/docs/configuration.md
 */
export const msalConfig = {
  auth: {
    clientId: CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: window.location.origin, // http://localhost:5173 or https://llmcouncil-frontend.azurewebsites.net
    postLogoutRedirectUri: window.location.origin,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: 'sessionStorage', // Use sessionStorage for better security
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return; // Never log PII
        switch (level) {
          case LogLevel.Error:
            console.error('[MSAL]', message);
            break;
          case LogLevel.Warning:
            console.warn('[MSAL]', message);
            break;
          case LogLevel.Info:
            // Only log info in development
            if (import.meta.env.DEV) {
              console.info('[MSAL]', message);
            }
            break;
          case LogLevel.Verbose:
            break;
        }
      },
      logLevel: import.meta.env.DEV ? LogLevel.Info : LogLevel.Warning,
    },
  },
};

/**
 * Scopes to request when acquiring tokens.
 * - openid + profile + email: standard OIDC claims (name, email, etc.)
 * - user_impersonation: custom API scope for our backend
 */
export const loginRequest = {
  scopes: [
    `api://${CLIENT_ID}/user_impersonation`,
  ],
};

/**
 * Scopes for acquiring access tokens for our backend API.
 */
export const apiTokenRequest = {
  scopes: [
    `api://${CLIENT_ID}/user_impersonation`,
  ],
};
