import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    channel: 'chrome',
  },
  webServer: {
    command: 'cd ../backend && PYTHONPATH=.:tests .venv/bin/python -m studio_test_server',
    url: 'http://127.0.0.1:8765/test/fixture.zip',
    timeout: 15000,
  },
});
