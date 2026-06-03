import { describe, expect, it } from 'vitest';
import { findMissingFunctionReferences } from './functionCoverage';

describe('frontend function coverage', () => {
  it('every frontend function has a unit test reference', () => {
    const missingFunctions = findMissingFunctionReferences();

    expect(
      missingFunctions,
      missingFunctions.length > 0
        ? `Missing unit test references for: ${missingFunctions.join(', ')}`
        : undefined,
    ).toEqual([]);
  });
});
