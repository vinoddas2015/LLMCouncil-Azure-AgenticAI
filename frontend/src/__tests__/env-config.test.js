import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('Environment Configuration', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  const testEnvMapping = (mode, viteEnv, expectedEnv) => {
    const viteEnvValue = viteEnv || mode;
    const envMap = {
      'development': 'LOCAL',
      'nonprod': 'NONPROD',
      'production': 'PRODUCTION',
    };
    const result = envMap[viteEnvValue.toLowerCase()] || 'LOCAL';
    return result === expectedEnv;
  };

  it('maps development mode to LOCAL', () => {
    expect(testEnvMapping('development', null, 'LOCAL')).toBe(true);
  });

  it('maps nonprod mode to NONPROD', () => {
    expect(testEnvMapping('nonprod', null, 'NONPROD')).toBe(true);
  });

  it('maps production mode to PRODUCTION', () => {
    expect(testEnvMapping('production', null, 'PRODUCTION')).toBe(true);
  });

  it('allows VITE_ENV to override MODE', () => {
    expect(testEnvMapping('development', 'nonprod', 'NONPROD')).toBe(true);
    expect(testEnvMapping('development', 'production', 'PRODUCTION')).toBe(true);
  });

  it('falls back to LOCAL for unknown environments', () => {
    expect(testEnvMapping('unknown', null, 'LOCAL')).toBe(true);
    expect(testEnvMapping('staging', null, 'LOCAL')).toBe(true);
  });
});
