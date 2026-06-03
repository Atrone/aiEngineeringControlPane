import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useApiQuery } from './useApiQuery';

describe('useApiQuery', () => {
  afterEach(() => {
    // Restore real timers so one hook test cannot affect the next one.
    vi.useRealTimers();
  });

  it('loads data and reports the loading lifecycle', async () => {
    const loader = vi.fn().mockResolvedValue({ name: 'dashboard' });

    const { result } = renderHook(() => useApiQuery(loader, []));

    expect(result.current).toEqual({ data: null, error: null, isLoading: true });

    await waitFor(() => {
      expect(result.current).toEqual({ data: { name: 'dashboard' }, error: null, isLoading: false });
    });
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('normalizes Error objects thrown by the loader', async () => {
    const loader = vi.fn().mockRejectedValue(new Error('Network failed'));

    const { result } = renderHook(() => useApiQuery(loader, []));

    await waitFor(() => {
      expect(result.current).toEqual({ data: null, error: 'Network failed', isLoading: false });
    });
  });

  it('normalizes unknown thrown values from the loader', async () => {
    const loader = vi.fn().mockRejectedValue('bad response');

    const { result } = renderHook(() => useApiQuery(loader, []));

    await waitFor(() => {
      expect(result.current).toEqual({ data: null, error: 'Unknown request error.', isLoading: false });
    });
  });

  it('reloads when dependencies change', async () => {
    const loader = vi.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second');
    const { rerender, result } = renderHook(({ dependency }) => useApiQuery(loader, [dependency]), {
      initialProps: { dependency: 'a' },
    });

    await waitFor(() => {
      expect(result.current.data).toBe('first');
    });

    rerender({ dependency: 'b' });

    await waitFor(() => {
      expect(result.current.data).toBe('second');
    });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('polls after a successful load when a polling interval is configured', async () => {
    vi.useFakeTimers();
    const loader = vi.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second');

    const { result } = renderHook(() => useApiQuery(loader, [], { pollIntervalMs: 1000 }));

    await act(async () => {
      // Flush the initial loader promise so the polling timeout is scheduled.
      await Promise.resolve();
    });
    expect(result.current.data).toBe('first');

    await act(async () => {
      // Advance the scheduled polling timer and flush the resulting promise chain.
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.data).toBe('second');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('clears scheduled polling when the hook unmounts', async () => {
    vi.useFakeTimers();
    const loader = vi.fn().mockResolvedValue('payload');

    const { unmount } = renderHook(() => useApiQuery(loader, [], { pollIntervalMs: 1000 }));

    await act(async () => {
      // Flush the initial loader promise so cleanup has a scheduled timer to clear.
      await Promise.resolve();
    });
    expect(loader).toHaveBeenCalledTimes(1);

    unmount();

    await act(async () => {
      // Move past the original interval to prove the cleanup cancelled the next load.
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('useApiQuery runLoader refreshes data when polling is enabled', async () => {
    vi.useFakeTimers();
    const loader = vi.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second');

    const { result } = renderHook(() => useApiQuery(loader, [], { pollIntervalMs: 500 }));

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.data).toBe('first');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.data).toBe('second');
  });
});
