import { useEffect, useState } from 'react';
import { fetchIntegrations } from '../lib/api';
import { findIntegrationStatus, getConnectionValue } from '../lib/appHelpers';
import type {
  CursorConnectRequest,
  GitHubConnectRequest,
  GitHubCopilotConnectRequest,
  JiraConnectRequest,
  LinearConnectRequest,
} from '../types/controlPane';
import { useApiQuery } from './useApiQuery';

/**
 * Keeps integration setup forms synchronized with the fetched provider status payload.
 */
function useIntegrationForms() {
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [githubForm, setGithubForm] = useState<GitHubConnectRequest>({
    owner: '',
    repositories: '',
    token: '',
  });
  const [linearForm, setLinearForm] = useState<LinearConnectRequest>({
    apiKey: '',
    teamId: '',
  });
  const [jiraForm, setJiraForm] = useState<JiraConnectRequest>({
    siteUrl: '',
    email: '',
    apiToken: '',
    projectKey: '',
  });
  const [cursorForm, setCursorForm] = useState<CursorConnectRequest>({
    apiKey: '',
    model: 'default',
  });
  const [githubCopilotForm, setGithubCopilotForm] = useState<GitHubCopilotConnectRequest>({
    token: '',
    model: '',
    customAgent: '',
  });
  const [mutationError, setMutationError] = useState<string>('');
  const [mutationSuccess, setMutationSuccess] = useState<string>('');
  const [activeSetupId, setActiveSetupId] = useState<string>('');
  const query = useApiQuery(fetchIntegrations, [refreshKey]);

  useEffect(() => {
    const githubStatus = findIntegrationStatus(query.data?.statuses ?? [], 'github');
    const linearStatus = findIntegrationStatus(query.data?.statuses ?? [], 'linear');
    const jiraStatus = findIntegrationStatus(query.data?.statuses ?? [], 'jira');
    const cursorStatus = findIntegrationStatus(query.data?.statuses ?? [], 'cursor_cloud_agents');
    const githubCopilotStatus = findIntegrationStatus(query.data?.statuses ?? [], 'github_copilot_cloud_agent');

    // Mirror the saved GitHub connection into the setup form defaults.
    setGithubForm({
      owner: getConnectionValue(githubStatus, 'owner'),
      repositories: getConnectionValue(githubStatus, 'repositories'),
      token: '',
    });

    // Mirror the saved Linear connection into the setup form defaults.
    setLinearForm({
      apiKey: '',
      teamId: getConnectionValue(linearStatus, 'teamId'),
    });

    // Mirror the saved Jira connection into the setup form defaults.
    setJiraForm({
      siteUrl: getConnectionValue(jiraStatus, 'siteUrl'),
      email: getConnectionValue(jiraStatus, 'email'),
      apiToken: '',
      projectKey: getConnectionValue(jiraStatus, 'projectKey'),
    });

    // Mirror the saved Cursor connection into the setup form defaults.
    setCursorForm({
      apiKey: '',
      model: getConnectionValue(cursorStatus, 'model') || 'default',
    });

    // Mirror the saved GitHub Copilot connection into the setup form defaults.
    setGithubCopilotForm({
      token: '',
      model: getConnectionValue(githubCopilotStatus, 'model'),
      customAgent: getConnectionValue(githubCopilotStatus, 'customAgent'),
    });
  }, [query.data]);

  // Return form state and mutation state as one object for the settings page.
  return {
    activeSetupId,
    cursorForm,
    githubCopilotForm,
    githubForm,
    jiraForm,
    linearForm,
    mutationError,
    mutationSuccess,
    query,
    setActiveSetupId,
    setCursorForm,
    setGithubCopilotForm,
    setGithubForm,
    setJiraForm,
    setLinearForm,
    setMutationError,
    setMutationSuccess,
    setRefreshKey,
  };
}

export { useIntegrationForms };
