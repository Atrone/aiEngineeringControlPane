import { useEffect, useId, useMemo, useState } from 'react';
import {
  buildRunTeamGroups,
} from '../lib/appHelpers';
import {
  buildMissionControlOwnerOptions,
  buildMissionControlRepoOptions,
  filterMissionControlRuns,
} from '../lib/dashboardMissionControlFilters';
import type { MissionControlFilterCriteria } from '../lib/dashboardMissionControlFilters';
import {
  fetchDashboard,
  fetchDashboardReviewEfforts,
  fetchDashboardSuggestedActions,
} from '../lib/api';
import type { ReviewEffortEstimate, RiskLevel, RunStatus } from '../types/controlPane';
import { useApiQuery } from './useApiQuery';

/**
 * Owns dashboard fetch state, mission-control filters, and OpenAI dashboard enrichments.
 */
function useMissionControlDashboard() {
  const query = useApiQuery(fetchDashboard, []);
  const [suggestedActions, setSuggestedActions] = useState<string[]>([]);
  const [suggestionsError, setSuggestionsError] = useState<string>('');
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState<boolean>(false);
  const [reviewEffortsByRunId, setReviewEffortsByRunId] = useState<Record<string, ReviewEffortEstimate>>({});
  const [reviewEffortsError, setReviewEffortsError] = useState<string>('');
  const [isReviewEffortsLoading, setIsReviewEffortsLoading] = useState<boolean>(false);
  const [selectedTeamKey, setSelectedTeamKey] = useState<string>('');
  const [missionSearch, setMissionSearch] = useState<string>('');
  const [missionStatus, setMissionStatus] = useState<'' | RunStatus>('');
  const [missionRepo, setMissionRepo] = useState<string>('');
  const [missionOwnerToken, setMissionOwnerToken] = useState<string>('');
  const [missionRisk, setMissionRisk] = useState<'' | RiskLevel>('');
  const missionFilterFormId = useId();
  const lobbyRuns = query.data
    ? query.data.runs
    : [];
  const teamGroups = buildRunTeamGroups(lobbyRuns);
  const selectedTeam = teamGroups.find((group) => group.key === selectedTeamKey) ?? teamGroups[0] ?? null;
  const selectedTeamRuns = selectedTeam?.runs ?? [];

  const missionControlFilterCriteria = useMemo<MissionControlFilterCriteria>(
    () => ({
      searchText: missionSearch,
      status: missionStatus,
      repo: missionRepo,
      ownerToken: missionOwnerToken,
      risk: missionRisk,
    }),
    [missionSearch, missionStatus, missionRepo, missionOwnerToken, missionRisk],
  );

  const filteredTeamRuns = useMemo(
    () => filterMissionControlRuns(selectedTeamRuns, missionControlFilterCriteria),
    [missionControlFilterCriteria, selectedTeamRuns],
  );

  // Build a stable, comma-joined key so the effect reruns only when the filtered run IDs change.
  const visibleRunIdsKey = filteredTeamRuns.map((run) => run.id).join(',');
  const missionRepoOptions = buildMissionControlRepoOptions(selectedTeamRuns);
  const missionOwnerOptions = buildMissionControlOwnerOptions(selectedTeamRuns);

  useEffect(() => {
    if (!visibleRunIdsKey) {
      // Skip OpenAI calls when there are no visible issue-tracker-linked runs.
      setSuggestedActions([]);
      setSuggestionsError('');
      setIsSuggestionsLoading(false);
      setReviewEffortsByRunId({});
      setReviewEffortsError('');
      setIsReviewEffortsLoading(false);
      return;
    }

    let isActive = true;
    const runIds = visibleRunIdsKey.split(',').filter((id) => id.length > 0);

    setIsSuggestionsLoading(true);
    setSuggestionsError('');
    setIsReviewEffortsLoading(true);
    setReviewEffortsError('');

    /**
     * Requests OpenAI-generated suggestions for the currently visible runs.
     */
    async function loadSuggestions(): Promise<void> {
      try {
        // Send the visible run IDs so the backend can prompt OpenAI with matching context.
        const response = await fetchDashboardSuggestedActions({ runIds });

        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        setSuggestedActions(response.suggestedActions);
      } catch (error) {
        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const readableMessage = error instanceof Error ? error.message : 'Suggested actions were unavailable.';
        setSuggestedActions([]);
        setSuggestionsError(readableMessage);
      } finally {
        if (isActive) {
          // Always clear the loading flag once the request settles.
          setIsSuggestionsLoading(false);
        }
      }
    }

    /**
     * Requests OpenAI-generated review-effort guesses for the selected lobby runs.
     */
    async function loadReviewEfforts(): Promise<void> {
      try {
        // Send the selected lobby run IDs so OpenAI can estimate effort from their PR summaries.
        const response = await fetchDashboardReviewEfforts({ runIds });

        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const nextReviewEffortsByRunId: Record<string, ReviewEffortEstimate> = {};

        // Index the estimates by run ID for cheap lookups during lobby rendering.
        for (const reviewEffort of response.reviewEfforts) {
          nextReviewEffortsByRunId[reviewEffort.runId] = reviewEffort;
        }

        setReviewEffortsByRunId(nextReviewEffortsByRunId);
      } catch (error) {
        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const readableMessage = error instanceof Error ? error.message : 'Review-effort estimates were unavailable.';
        setReviewEffortsByRunId({});
        setReviewEffortsError(readableMessage);
      } finally {
        if (isActive) {
          // Always clear the loading flag once the request settles.
          setIsReviewEffortsLoading(false);
        }
      }
    }

    void loadSuggestions();
    void loadReviewEfforts();

    return () => {
      // Mark the effect as inactive so stale responses do not overwrite fresh state.
      isActive = false;
    };
  }, [visibleRunIdsKey]);

  // Return dashboard state in one object so the page can focus on rendering.
  return {
    filteredTeamRuns,
    isReviewEffortsLoading,
    isSuggestionsLoading,
    lobbyRuns,
    missionFilterFormId,
    missionOwnerOptions,
    missionOwnerToken,
    missionRepo,
    missionRepoOptions,
    missionRisk,
    missionSearch,
    missionStatus,
    query,
    reviewEffortsByRunId,
    reviewEffortsError,
    selectedTeam,
    selectedTeamRuns,
    setMissionOwnerToken,
    setMissionRepo,
    setMissionRisk,
    setMissionSearch,
    setMissionStatus,
    setSelectedTeamKey,
    suggestedActions,
    suggestionsError,
    teamGroups,
  };
}

export { useMissionControlDashboard };
