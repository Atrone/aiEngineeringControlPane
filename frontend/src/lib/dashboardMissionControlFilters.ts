import type { RiskLevel, RunStatus, RunSummary } from '../types/controlPane';

/**
 * Shape of the mission control quick-filter state applied to the dashboard run list.
 */
export type MissionControlFilterCriteria = {
  /** Free-text query matched across ticket, title, repo, agent, and owner fields. */
  searchText: string;
  /** When set, only runs whose status equals this value are kept. */
  status: '' | RunStatus;
  /** When set, only runs whose repository name equals this value are kept. */
  repo: string;
  /**
   * When "__unassigned__", matches runs with a blank owner; when non-empty otherwise,
   * matches that exact trimmed owner label.
   */
  ownerToken: string;
  /** When set, only runs at this risk level are kept. */
  risk: '' | RiskLevel;
};

/**
 * Normalizes free-text search input for consistent comparisons.
 */
function normalizeMissionControlSearchText(searchText: string): string {
  // Collapse whitespace so accidental double spaces still match predictably.
  return searchText.trim().toLowerCase();
}

/**
 * Reports whether a run matches the optional substring search across key labels.
 */
function runMatchesMissionControlSearch(run: RunSummary, normalizedQuery: string): boolean {
  if (!normalizedQuery) {
    // Skip search filtering when the operator cleared the search field.
    return true;
  }

  const haystack = [
    run.ticket,
    run.title,
    run.repo,
    run.agent,
    run.owner,
  ]
    .map((fragment) => fragment.trim().toLowerCase())
    .join(' ');

  // Require every whitespace-separated token to appear somewhere in the combined haystack.
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);

  for (const token of tokens) {
    if (!haystack.includes(token)) {
      // Reject the run when any required token is missing from the searchable text.
      return false;
    }
  }

  // Accept the run when every search token matched the combined fields.
  return true;
}

/**
 * Reports whether a run passes the optional status filter.
 */
function runMatchesMissionControlStatus(run: RunSummary, status: MissionControlFilterCriteria['status']): boolean {
  if (!status) {
    // Treat an empty status filter as "all statuses" for the dashboard list.
    return true;
  }

  // Keep only runs whose lifecycle status matches the selected filter value.
  return run.status === status;
}

/**
 * Reports whether a run passes the optional repository filter.
 */
function runMatchesMissionControlRepo(run: RunSummary, repo: string): boolean {
  const selectedRepo = repo.trim();

  if (!selectedRepo) {
    // Treat an empty repository filter as "all repositories" for the team lobby.
    return true;
  }

  // Compare trimmed repository names so minor whitespace differences still align.
  return run.repo.trim() === selectedRepo;
}

/**
 * Reports whether a run passes the optional owner filter, including unassigned handling.
 */
function runMatchesMissionControlOwner(run: RunSummary, ownerToken: string): boolean {
  const token = ownerToken.trim();

  if (!token) {
    // Treat an empty owner filter as "all owners" for the team lobby.
    return true;
  }

  const ownerLabel = run.owner.trim();

  if (token === '__unassigned__') {
    // Surface runs that lack an explicit owner label for triage-style filtering.
    return ownerLabel.length === 0;
  }

  // Match the human-readable owner label exactly after trimming whitespace.
  return ownerLabel === token;
}

/**
 * Reports whether a run passes the optional risk filter.
 */
function runMatchesMissionControlRisk(run: RunSummary, risk: MissionControlFilterCriteria['risk']): boolean {
  if (!risk) {
    // Treat an empty risk filter as "all risk levels" for the team lobby.
    return true;
  }

  // Keep only runs tagged with the selected risk level.
  return run.risk === risk;
}

/**
 * Applies mission control quick filters to the runs visible in the active team lobby.
 */
export function filterMissionControlRuns(runs: RunSummary[], criteria: MissionControlFilterCriteria): RunSummary[] {
  const normalizedQuery = normalizeMissionControlSearchText(criteria.searchText);
  const filtered: RunSummary[] = [];

  // Walk the lobby runs and keep only rows that satisfy every active filter dimension.
  for (const run of runs) {
    if (!runMatchesMissionControlSearch(run, normalizedQuery)) {
      continue;
    }

    if (!runMatchesMissionControlStatus(run, criteria.status)) {
      continue;
    }

    if (!runMatchesMissionControlRepo(run, criteria.repo)) {
      continue;
    }

    if (!runMatchesMissionControlOwner(run, criteria.ownerToken)) {
      continue;
    }

    if (!runMatchesMissionControlRisk(run, criteria.risk)) {
      continue;
    }

    // Append the run because it satisfied the full filter stack.
    filtered.push(run);
  }

  // Return the filtered list in the same relative order as the incoming lobby ordering.
  return filtered;
}

/**
 * Builds sorted unique repository names for filter dropdown options.
 */
export function buildMissionControlRepoOptions(runs: RunSummary[]): string[] {
  const unique = new Set<string>();

  // Collect trimmed repository names from every run in the active lobby.
  for (const run of runs) {
    const name = run.repo.trim();

    if (name) {
      unique.add(name);
    }
  }

  // Return alphabetically sorted options so the dropdown stays easy to scan.
  return Array.from(unique).sort((a, b) => a.localeCompare(b));
}

/**
 * Builds sorted unique owner labels for filter dropdown options.
 */
export function buildMissionControlOwnerOptions(runs: RunSummary[]): { label: string; value: string }[] {
  const unique = new Set<string>();
  let hasUnassigned = false;

  // Collect owner labels while tracking whether any run lacks an owner string.
  for (const run of runs) {
    const owner = run.owner.trim();

    if (!owner) {
      hasUnassigned = true;
      continue;
    }

    unique.add(owner);
  }

  const options: { label: string; value: string }[] = [];

  // Add stable alphabetical entries for every non-empty owner label.
  for (const value of Array.from(unique).sort((a, b) => a.localeCompare(b))) {
    options.push({ label: value, value });
  }

  if (hasUnassigned) {
    // Surface a dedicated option so operators can filter to unowned runs quickly.
    options.unshift({ label: '(Unassigned)', value: '__unassigned__' });
  }

  // Return the assembled owner filter options for the mission control toolbar.
  return options;
}
