const domainNonProd = 'breeding-np.ag'
const domainProd = 'breeding.ag'
const routePrefixNonProd = 'llm-council-np'
const routePrefixProd = 'llm-council'

const environments = {
    LOCAL: {
        basename: "/",
        apiBaseUrl: "http://localhost:8001",
        authTokenRefreshUrl: `http://${domainNonProd}/${routePrefixNonProd}/auth-token-refresh`,
    },
    NONPROD: {
        basename: `/${routePrefixNonProd}`,
        apiBaseUrl: `https://${domainNonProd}/llmc-api`,
        authTokenRefreshUrl: `https://${domainNonProd}/${routePrefixNonProd}/auth-token-refresh`,
    },
    PRODUCTION: {
        basename: `/${routePrefixProd}`,
        apiBaseUrl: `https://${domainProd}/llmc-api`,
        authTokenRefreshUrl: `https://${domainProd}/${routePrefixProd}/auth-token-refresh`,
    }
}

/**
 * Get the current environment configuration based on Vite's mode.
 * 
 * Environment mapping:
 * - development (npm run dev) → LOCAL
 * - nonprod (npm run build:nonprod) → NONPROD  
 * - production (npm run build) → PRODUCTION
 * 
 * Override via VITE_ENV environment variable if needed.
 */
function getEnvironmentConfig() {
    const viteEnv = import.meta.env.VITE_ENV || import.meta.env.MODE;
    
    const envMap = {
        'development': 'LOCAL',
        'nonprod': 'NONPROD',
        'production': 'PRODUCTION',
    };
    
    const envKey = envMap[viteEnv.toLowerCase()] || 'LOCAL';
    
    return environments[envKey];
}

export const config = getEnvironmentConfig();
export const currentEnvironment = import.meta.env.VITE_ENV || import.meta.env.MODE;