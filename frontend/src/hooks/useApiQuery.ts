import { useEffect, useState } from 'react';

type QueryState<T> = {
  data: T | null;
  error: string | null;
  isLoading: boolean;
};

/**
 * Loads async data for a page-level query and tracks loading state.
 */
export function useApiQuery<T>(loader: () => Promise<T>, dependencies: readonly unknown[]): QueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    let isActive = true;

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
      }
    }

    // Start the async load for the current dependency set.
    void runLoader();

    return () => {
      // Ignore late responses after the component unmounts or dependencies change.
      isActive = false;
    };
  }, dependencies);

  // Return the standard query state shape to the caller.
  return { data, error, isLoading };
}
