import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  // Unmount rendered React trees so component tests do not leak DOM into later cases.
  cleanup();
});
