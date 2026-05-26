import type { KeyboardEvent, ReactNode } from 'react';
import { useId } from 'react';
import {
  buildEvidenceStatusClassName,
  buildEvidenceTabLabel,
  buildLogEntryClassName,
  buildRoleLabel,
  buildTimelineEntryClassName,
  formatEventTime,
} from '../../lib/appHelpers';
import type {
  CurrentUser,
  DashboardMetric,
  DocumentRecord,
  IntegrationStatus,
  RiskLevel,
  RunLiveView,
  RunLogEntry,
  RunStatus,
  RunTimelineEntry,
} from '../../types/controlPane';
import type { EvidenceTabId } from '../../lib/appHelpers';

/**
 * Renders a compact status and risk badge.
 */
function StatusBadge(props: { status: RunStatus; risk: RiskLevel }) {
  const statusClassName = `status-badge status-${props.status.toLowerCase()} risk-${props.risk.toLowerCase()}`;

  // Keep status and risk together because both inform reviewer urgency.
  return <span className={statusClassName}>{props.status} · {props.risk}</span>;
}

/**
 * Renders a small metric summary card.
 */
function MetricCard(props: DashboardMetric) {
  // Make dashboard metrics scannable at a glance.
  return (
    <article className="metric-card">
      <p className="metric-label">{props.label}</p>
      <p className="metric-value">{props.value}</p>
      <p className="muted-copy">{props.hint}</p>
    </article>
  );
}

/**
 * Renders a provider integration status card.
 */
function IntegrationStatusCard(props: { status: IntegrationStatus }) {
  const capabilityItems: ReactNode[] = [];

  // Render each capability as a scan-friendly list item.
  for (const capability of props.status.capabilities) {
    capabilityItems.push(<li key={capability}>{capability}</li>);
  }

  // Return the provider integration status card.
  return (
    <article className="integration-card">
      <div className="integration-card-header">
        <div>
          <p className="ticket-code">{props.status.name}</p>
          <h3>{props.status.connected ? 'Connected' : 'Fallback mode'}</h3>
        </div>
        <span className={`pill integration-pill integration-pill-${props.status.mode}`}>{props.status.mode}</span>
      </div>
      <p className="muted-copy">{props.status.details}</p>
      <p className="subtle-copy">Required role: {buildRoleLabel(props.status.requiredRole)}</p>
      <p className="subtle-copy">{props.status.recommendedAction}</p>
      {props.status.connection ? <p className="subtle-copy">Connected as: {props.status.connection.label}</p> : null}
      <ul className="detail-list compact-list">{capabilityItems}</ul>
      <p className="subtle-copy">Checked: {props.status.checkedAt}</p>
    </article>
  );
}

/**
 * Renders a shared loading panel for route-level data fetches.
 */
function LoadingState(props: { message: string }) {
  // Keep loading feedback consistent across screens that fetch backend data.
  return (
    <section aria-busy="true" aria-live="polite" className="panel state-panel" role="status">
      <p className="eyebrow">Loading</p>
      <h3>{props.message}</h3>
      <p className="muted-copy">The UI is waiting for the FastAPI integration layer to respond.</p>
    </section>
  );
}

/**
 * Renders a shared error panel for route-level data fetches.
 */
function ErrorState(props: { message: string }) {
  // Keep failed requests visible without breaking the surrounding shell.
  return (
    <section className="panel state-panel" role="alert">
      <p className="eyebrow">Request failed</p>
      <h3>Unable to load this control-pane view.</h3>
      <p className="muted-copy">{props.message}</p>
    </section>
  );
}

/**
 * Renders a standalone full-page state panel for auth flows.
 */
function StandaloneStatePanel(props: { eyebrow: string; title: string; body: string }) {
  // Keep loading and transition states visually consistent outside the app shell.
  return (
    <div className="auth-shell">
      <section className="auth-panel auth-panel-centered">
        <p className="eyebrow">{props.eyebrow}</p>
        <h1>{props.title}</h1>
        <p className="muted-copy">{props.body}</p>
      </section>
    </div>
  );
}

/**
 * Renders a friendly access-denied state for gated routes.
 */
function AccessDeniedState(props: { currentUser: CurrentUser; title: string }) {
  // Keep gated routes readable instead of dropping the user onto a blank page.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Access denied</p>
      <h3>{props.title} is limited to reviewers.</h3>
      <p className="muted-copy">
        {buildRoleLabel(props.currentUser.role)} sessions can still inspect dashboards and task detail, but only admin sessions can manage approvals and integrations.
      </p>
    </section>
  );
}

/**
 * Renders the run timeline with timestamps and live-state styling.
 */
function TimelineList(props: { entries: RunTimelineEntry[]; liveLabel: string }) {
  if (props.entries.length === 0) {
    // Return a neutral placeholder when no timeline data is available yet.
    return <p className="muted-copy">No timeline data is available for this run yet.</p>;
  }

  const timelineItems: ReactNode[] = [];

  // Render each timeline step with its local timestamp and current execution state.
  for (const entry of props.entries) {
    timelineItems.push(
      <li className={buildTimelineEntryClassName(entry.status)} key={entry.id}>
        <div className="timeline-entry-header">
          <strong>{entry.title}</strong>
          <span className="subtle-copy">{formatEventTime(entry.timestamp)}</span>
        </div>
        <p className="muted-copy">{entry.detail}</p>
      </li>,
    );
  }

  // Return the full run timeline together with the current live-state label.
  return (
    <div className="timeline-shell">
      <div className="timeline-meta">
        <span className="pill">{props.liveLabel}</span>
      </div>
      <ul className="timeline-list">{timelineItems}</ul>
    </div>
  );
}

/**
 * Renders the streamed execution log panel for a run.
 */
function LogStream(props: { entries: RunLogEntry[] }) {
  if (props.entries.length === 0) {
    // Return a neutral placeholder when no log lines have been recorded.
    return <p className="muted-copy">No streamed logs have been captured for this run yet.</p>;
  }

  const logItems: ReactNode[] = [];

  // Render each log line in chronological order with its source and level styling.
  for (const entry of props.entries) {
    logItems.push(
      <div className={buildLogEntryClassName(entry.level)} key={entry.id}>
        <div className="log-entry-header">
          <span>{formatEventTime(entry.timestamp)}</span>
          <span>{entry.source}</span>
        </div>
        <p>{entry.message}</p>
      </div>,
    );
  }

  // Return the live log stream panel for the selected run.
  return <div className="log-stream">{logItems}</div>;
}

/**
 * Renders the tabbed evidence view grouped by diff, tests, and rationale.
 */
function EvidenceTabPanel(props: { liveView: RunLiveView; activeTab: EvidenceTabId; onTabChange: (tab: EvidenceTabId) => void }) {
  const evidencePanelId = useId();
  const availableTabs: EvidenceTabId[] = ['diff', 'tests', 'rationale'];
  const activeEntries = props.liveView.evidenceTabs[props.activeTab];
  const tabButtons: ReactNode[] = [];
  const evidenceRows: ReactNode[] = [];

  /**
   * Builds a stable DOM id for each evidence tab control.
   */
  function buildEvidenceTabId(tab: EvidenceTabId): string {
    // Join the React id prefix with the tab key so each control stays unique in the DOM.
    return `${evidencePanelId}-${tab}-tab`;
  }

  /**
   * Builds a stable DOM id for each evidence tab panel region.
   */
  function buildEvidencePanelId(tab: EvidenceTabId): string {
    // Join the React id prefix with the tab key so each panel stays unique in the DOM.
    return `${evidencePanelId}-${tab}-panel`;
  }

  /**
   * Moves focus across evidence tabs using arrow keys for keyboard parity with mouse users.
   */
  function handleEvidenceTabKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    // Ignore keys that are not part of the roving tablist interaction model.
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'Home' && event.key !== 'End') {
      return;
    }

    // Prevent the browser from scrolling the page horizontally while changing tabs.
    event.preventDefault();

    const activeIndex = availableTabs.indexOf(props.activeTab);

    if (activeIndex < 0) {
      // Bail out when the active tab is not part of the supported tab list.
      return;
    }

    let nextIndex = activeIndex;

    if (event.key === 'ArrowRight') {
      // Advance to the next tab and wrap from the end back to the start.
      nextIndex = (activeIndex + 1) % availableTabs.length;
    } else if (event.key === 'ArrowLeft') {
      // Move to the previous tab and wrap from the start back to the end.
      nextIndex = (activeIndex - 1 + availableTabs.length) % availableTabs.length;
    } else if (event.key === 'Home') {
      // Jump directly to the first tab for faster scanning from the keyboard.
      nextIndex = 0;
    } else {
      // Jump directly to the last tab when End is pressed.
      nextIndex = availableTabs.length - 1;
    }

    const nextTab = availableTabs[nextIndex];

    // Update the selected tab so the panel content stays synchronized with focus intent.
    props.onTabChange(nextTab);

    // Move keyboard focus to the newly selected tab button after React re-renders.
    window.requestAnimationFrame(() => {
      document.getElementById(buildEvidenceTabId(nextTab))?.focus();
    });
  }

  // Render the evidence tab buttons with counts from the current live-view snapshot.
  for (const tab of availableTabs) {
    const isSelected = tab === props.activeTab;

    tabButtons.push(
      <button
        aria-controls={buildEvidencePanelId(tab)}
        aria-selected={isSelected}
        className={isSelected ? 'evidence-tab evidence-tab-active' : 'evidence-tab'}
        id={buildEvidenceTabId(tab)}
        key={tab}
        onClick={() => { props.onTabChange(tab); }}
        role="tab"
        type="button"
      >
        {buildEvidenceTabLabel(tab)} ({props.liveView.evidenceTabs[tab].length})
      </button>,
    );
  }

  // Render the selected evidence tab entries with timestamps and capture state.
  for (const entry of activeEntries) {
    evidenceRows.push(
      <div className="evidence-row" key={entry.id}>
        <div className="evidence-row-header">
          <strong>{entry.summary}</strong>
          <span className={buildEvidenceStatusClassName(entry.status)}>{entry.status}</span>
        </div>
        <p className="muted-copy">{entry.detail}</p>
        <p className="subtle-copy">{formatEventTime(entry.timestamp)}</p>
      </div>,
    );
  }

  // Return the grouped tab controls and the currently selected evidence list.
  return (
    <div className="evidence-shell">
      <div aria-label="Evidence categories" className="evidence-tab-list" onKeyDown={handleEvidenceTabKeyDown} role="tablist">
        {tabButtons}
      </div>
      <div
        aria-labelledby={buildEvidenceTabId(props.activeTab)}
        className="evidence-tab-panel"
        id={buildEvidencePanelId(props.activeTab)}
        role="tabpanel"
        tabIndex={0}
      >
        {evidenceRows.length > 0 ? <div className="evidence-row-list">{evidenceRows}</div> : <p className="muted-copy">No evidence has streamed into this tab yet.</p>}
      </div>
    </div>
  );
}

/**
 * Renders a simple unordered list for evidence and blocker sections.
 */
function DetailList(props: { items: string[] }) {
  const listItems: ReactNode[] = [];

  // Convert each string entry into a consistently styled list item.
  for (const item of props.items) {
    listItems.push(<li key={item}>{item}</li>);
  }

  // Return the rendered detail list for the surrounding panel.
  return <ul className="detail-list">{listItems}</ul>;
}

/**
 * Renders the attached document list for a task.
 */
function DocumentList(props: { documents: DocumentRecord[] }) {
  if (props.documents.length === 0) {
    // Return a neutral placeholder when no documents are attached.
    return <p className="muted-copy">No documents were attached to this task.</p>;
  }

  const documentItems: ReactNode[] = [];

  // Render each attached document as a simple scan-friendly row.
  for (const document of props.documents) {
    documentItems.push(
      <div className="mini-row" key={document.id}>
        <strong>{document.title}</strong>
        <span className="subtle-copy">{document.path}</span>
      </div>,
    );
  }

  // Return the rendered document list.
  return <div className="mini-list">{documentItems}</div>;
}

/**
 * Wraps page sections in a consistent panel treatment.
 */
function Panel(props: { title: string; body: ReactNode }) {
  // Keep content framing consistent across dashboard and review views.
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>{props.title}</h3>
      </div>
      <div className="panel-body">{props.body}</div>
    </section>
  );
}

export {
  AccessDeniedState,
  DetailList,
  DocumentList,
  ErrorState,
  EvidenceTabPanel,
  IntegrationStatusCard,
  LoadingState,
  LogStream,
  MetricCard,
  Panel,
  StandaloneStatePanel,
  StatusBadge,
  TimelineList,
};
