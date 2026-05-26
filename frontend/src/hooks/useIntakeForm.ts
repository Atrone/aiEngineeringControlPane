import { useEffect, useState } from 'react';
import { classifyIntakeIssuesByScope, fetchIntakeOptions } from '../lib/api';
import { findIssueById } from '../lib/appHelpers';
import type { IntakeEnrichField, IntakeIssueScopingResponse, UploadedDocumentRecord } from '../types/controlPane';
import { useApiQuery } from './useApiQuery';

/**
 * Owns intake form field state, default issue hydration, and issue scope loading.
 */
function useIntakeForm() {
  const query = useApiQuery(fetchIntakeOptions, []);
  const [selectedIssueId, setSelectedIssueId] = useState<string>('');
  const [selectedRepoName, setSelectedRepoName] = useState<string>('');
  const [title, setTitle] = useState<string>('');
  const [prompt, setPrompt] = useState<string>('');
  const [acceptanceCriteria, setAcceptanceCriteria] = useState<string>('');
  const [executionMode, setExecutionMode] = useState<string>('implement');
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [enrichingField, setEnrichingField] = useState<IntakeEnrichField | ''>('');
  const [enrichError, setEnrichError] = useState<string>('');
  const [enrichNotice, setEnrichNotice] = useState<string>('');
  const [isIdentifyingRepo, setIsIdentifyingRepo] = useState<boolean>(false);
  const [identifyError, setIdentifyError] = useState<string>('');
  const [identifyNotice, setIdentifyNotice] = useState<string>('');
  const [uploadedDocuments, setUploadedDocuments] = useState<UploadedDocumentRecord[]>([]);
  const [uploadError, setUploadError] = useState<string>('');

  /**
   * Loads the OpenAI-scored issue scoping groups for the visible intake issues.
   */
  async function loadIssueScoping(): Promise<IntakeIssueScopingResponse | null> {
    if (!query.data || query.data.issues.length === 0) {
      // Skip scoping requests until the intake issue catalog has loaded.
      return null;
    }

    const issueIds: string[] = [];

    // Preserve the rendered issue order when asking the backend to classify the list.
    for (const issue of query.data.issues) {
      issueIds.push(issue.id);
    }

    // Ask the OpenAI-backed backend route to separate the issues into the two scope buckets.
    return classifyIntakeIssuesByScope({ issueIds });
  }

  const issueScopingQuery = useApiQuery(loadIssueScoping, [query.data]);

  useEffect(() => {
    if (!query.data) {
      // Skip form bootstrapping until the intake payload is available.
      return;
    }

    if (!selectedRepoName && query.data.repositories.length > 0) {
      // Default the repo selection to the first available repository option.
      setSelectedRepoName(query.data.repositories[0].name);
    }
  }, [query.data, selectedRepoName]);

  useEffect(() => {
    if (!query.data || !selectedIssueId) {
      // Skip issue-driven form updates when no issue is selected.
      return;
    }

    const issue = findIssueById(query.data.issues, selectedIssueId);

    if (!issue) {
      // Skip updates when the selected issue cannot be found.
      return;
    }

    // Refresh the intake title so it always matches the currently selected issue.
    setTitle(issue.title);

    // Refresh the implementation prompt from the selected issue details.
    setPrompt(issue.description || `Implement ${issue.ticket}: ${issue.title}`);

    // Refresh the acceptance criteria so it stays aligned with the selected issue.
    setAcceptanceCriteria(`Deliver ${issue.ticket} with clear review evidence and preserve issue traceability from ${issue.status}.`);
  }, [query.data, selectedIssueId]);

  // Return all form state so the intake page can keep its existing render structure.
  return {
    acceptanceCriteria,
    enrichError,
    enrichingField,
    enrichNotice,
    executionMode,
    identifyError,
    identifyNotice,
    isIdentifyingRepo,
    isSubmitting,
    issueScopingQuery,
    prompt,
    query,
    selectedIssueId,
    selectedRepoName,
    setAcceptanceCriteria,
    setEnrichError,
    setEnrichingField,
    setEnrichNotice,
    setExecutionMode,
    setIdentifyError,
    setIdentifyNotice,
    setIsIdentifyingRepo,
    setIsSubmitting,
    setPrompt,
    setSelectedIssueId,
    setSelectedRepoName,
    setSubmitError,
    setTitle,
    setUploadError,
    setUploadedDocuments,
    submitError,
    title,
    uploadError,
    uploadedDocuments,
  };
}

export { useIntakeForm };
