import { useEffect, useState } from 'react';

type QueryState<T> = {
  data: T | null;
  error: string | null;
  isLoading: boolean;
};

type QueryOptions = {
  pollIntervalMs?: number;
};

/**
 * Loads async data for a page-level query and tracks loading state.
 */
export function useApiQuery<T>(loader: () => Promise<T>, dependencies: readonly unknown[], options?: QueryOptions): QueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    let isActive = true;
    let pollTimer: number | undefined;

    /**
     * Runs the async loader and updates local state if the component is still mounted.
     */
    async function runLoader(): Promise<void> {
      // Reset the query state before the next request begins.
      setIsLoading(true);
      setError(null);

      try {
        // Wait for the caller-provided loader to resolve with fresh data.
        const result = await loader();

        if (isActive) {
          // Save the resolved payload for the screen to render.
          setData(result);
        }
      } catch (caughtError) {
        if (isActive) {
          // Convert any thrown value into a readable message for the UI.
          setError(caughtError instanceof Error ? caughtError.message : 'Unknown request error.');
        }
      } finally {
        if (isActive) {
          // Mark loading as complete after the request settles.
          setIsLoading(false);
        }

        if (isActive && options?.pollIntervalMs) {
          // Schedule the next refresh so live task views can keep streaming updates.
          pollTimer = window.setTimeout(() => {
            void runLoader();
          }, options.pollIntervalMs);
        }
      }
    }

    // Start the async load for the current dependency set.
    void runLoader();

    return () => {
      // Ignore late responses after the component unmounts or dependencies change.
      isActive = false;

      if (pollTimer) {
        // Clear the next scheduled poll when the query is torn down.
        window.clearTimeout(pollTimer);
      }
    };
  }, [...dependencies, options?.pollIntervalMs]);

  // Return the standard query state shape to the caller.
  return { data, error, isLoading };
}
