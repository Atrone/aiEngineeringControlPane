import type { DocumentRecord, IntegrationStatus, IssueRecord, UploadedDocumentRecord } from '../types/controlPane';

/**
 * Converts a browser file into the uploaded-document payload shape used by intake APIs.
 */
async function buildUploadedDocumentRecord(file: File): Promise<UploadedDocumentRecord> {
  // Read the raw file contents so enrichment can use the exact uploaded repo context.
  const content = await file.text();
  const normalizedName = file.name.trim() || 'uploaded-document.txt';
  const title = normalizedName.replace(/\.[^.]+$/, '') || normalizedName;
  const updatedAt = file.lastModified > 0
    ? new Date(file.lastModified).toISOString()
    : new Date().toISOString();

  return {
    id: `upload-${normalizedName}-${file.lastModified}-${file.size}`,
    title,
    path: `uploads/${normalizedName}`,
    source: 'uploaded_repo_document',
    updatedAt,
    content,
  };
}

/**
 * Returns the label the intake form should use for enrichment grounding.
 */
function buildEnrichmentSourceLabel(uploadedDocuments: UploadedDocumentRecord[]): string {
  if (uploadedDocuments.length > 0) {
    // Call out uploaded docs when the operator has overridden the default repo source.
    return 'uploaded docs';
  }

  // Fall back to the repository docs label when no uploads are present.
  return 'repo docs';
}

/**
 * Normalizes repository and docs-folder names for client-side matching.
 */
function normalizeRepoDocKey(value: string): string {
  // Collapse punctuation differences so repo names and docs folder names compare cleanly.
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

/**
 * Reports whether a document belongs to the shared top-level docs folder.
 */
function isSharedTopLevelDocsDocument(document: DocumentRecord): boolean {
  const normalizedPath = document.path.replace(/\\/g, '/').toLowerCase();
  const pathParts = normalizedPath.split('/');

  if (document.repoName) {
    // Repo-tagged docs are handled by the selected-repository match below.
    return false;
  }

  // Treat direct docs-folder markdown as shared context for every selected repo.
  return pathParts.length === 2 && pathParts[0] === 'docs' && (normalizedPath.endsWith('.md') || normalizedPath.endsWith('.markdown'));
}

/**
 * Returns the repo document records that belong to the selected repository.
 */
function getDocumentsForRepository(documents: DocumentRecord[], repoName: string): DocumentRecord[] {
  const selectedRepoKey = normalizeRepoDocKey(repoName);

  if (!selectedRepoKey) {
    // Return no repo-specific docs when the intake form has no selected repository.
    return [];
  }

  // Keep repo-tagged documents and shared top-level docs folder files for the selection.
  return documents.filter((document) => normalizeRepoDocKey(document.repoName ?? '') === selectedRepoKey || isSharedTopLevelDocsDocument(document));
}

/**
 * Finds an issue by ID from the intake issue catalog.
 */
function findIssueById(issues: IssueRecord[], issueId: string): IssueRecord | null {
  // Search the issue catalog for the selected issue record.
  for (const issue of issues) {
    if (issue.id === issueId) {
      // Return the matching issue record.
      return issue;
    }
  }

  // Return null when the requested issue cannot be found.
  return null;
}

/**
 * Finds an integration status record by provider ID.
 */
function findIntegrationStatus(statuses: IntegrationStatus[], integrationId: string): IntegrationStatus | null {
  // Search the fetched integration status list for the requested provider record.
  for (const status of statuses) {
    if (status.id === integrationId) {
      // Return the first matching provider status record.
      return status;
    }
  }

  // Return null when the requested provider record does not exist.
  return null;
}

/**
 * Reads a single saved connection field from an integration status.
 */
function getConnectionValue(status: IntegrationStatus | null, key: string): string {
  if (!status?.connection) {
    // Return an empty string when the provider has no saved connection payload.
    return '';
  }

  // Return the saved connection value or an empty string when it is missing.
  return status.connection.values[key] ?? '';
}

export {
  buildEnrichmentSourceLabel,
  buildUploadedDocumentRecord,
  findIntegrationStatus,
  findIssueById,
  getConnectionValue,
  getDocumentsForRepository,
};
