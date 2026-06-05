import type { ReactNode } from 'react';
import { exchangeGoogleAuthCode } from './api';
import type { AuthSession, CurrentUser, UserRole } from '../types/controlPane';

const googleAuthCallbackExchanges = new Map<string, Promise<AuthSession>>();
const reviewerRoles: UserRole[] = ['admin'];

/**
 * Exchanges a Google callback code once during the current browser page load.
 */
function exchangeGoogleAuthCodeOnce(code: string): Promise<AuthSession> {
  const cachedExchange = googleAuthCallbackExchanges.get(code);

  if (cachedExchange) {
    // Reuse the first request when React remounts the callback route in development.
    return cachedExchange;
  }

  // Start the backend exchange and keep the promise available for duplicate effects.
  const exchangePromise = exchangeGoogleAuthCode(code).catch((caughtError: unknown) => {
    // Allow a real failed exchange to be retried without reloading the app.
    googleAuthCallbackExchanges.delete(code);
    throw caughtError;
  });

  // Cache the in-flight exchange before returning it to callback route effects.
  googleAuthCallbackExchanges.set(code, exchangePromise);
  return exchangePromise;
}

/**
 * Builds the active nav class based on the current location.
 */
function getNavLinkClassName(pathname: string, targetPath: string): string {
  if (targetPath === '/settings' && pathname === '/integrations') {
    // Keep the settings nav state active for the legacy integrations route alias.
    return 'nav-link active';
  }

  // Highlight the current section so navigation stays oriented.
  return pathname === targetPath ? 'nav-link active' : 'nav-link';
}

/**
 * Builds the shared shell title for the current page route.
 */
function buildShellPageTitle(pathname: string): string {
  if (pathname.startsWith('/tasks/')) {
    // Label individual run detail pages as focused run rooms.
    return 'Run Room';
  }

  if (pathname === '/intake') {
    // Match the intake route to the ShipControl delivery flow label.
    return 'New Shipment';
  }

  if (pathname === '/settings' || pathname === '/integrations') {
    // Treat the legacy integrations alias as the settings page.
    return 'Settings';
  }

  // Keep the dashboard title as the default shell landing state.
  return 'Fleet Dashboard';
}

/**
 * Reports whether a given role can access a protected route or action.
 */
function canAccessRole(role: UserRole, allowedRoles: UserRole[]): boolean {
  // Return true when the signed-in role is included in the allowed role list.
  return allowedRoles.includes(role);
}

/**
 * Builds a human-readable label for the current role badge.
 */
function buildRoleLabel(role: UserRole): string {
  void role;

  // Return the only supported role label.
  return 'Admin';
}

/**
 * Builds the sign-in capability list for the admin session.
 */
function buildRoleCapabilityItems(): ReactNode[] {
  const capabilities: string[] = [
    'Access every route in ShipControl.',
    'Launch work, review approval-ready runs, and resolve decisions.',
    'Manage integrations, sign-in flows, and ShipControl governance.',
  ];
  const capabilityItems: ReactNode[] = [];

  // Convert each capability string into a rendered list item.
  for (const capability of capabilities) {
    capabilityItems.push(<li key={capability}>{capability}</li>);
  }

  // Return the rendered role capability list for the auth screen.
  return capabilityItems;
}

/**
 * Builds the sidebar headline from the resolved current user.
 */
function buildUserHeadline(user: CurrentUser | null): string {
  if (!user) {
    // Fall back to a neutral headline when the current user has not loaded yet.
    return 'Loading user';
  }

  // Return the current user's display name for the sidebar summary.
  return user.name;
}

/**
 * Builds the sidebar subtitle from the resolved current user.
 */
function buildUserSubtitle(user: CurrentUser | null): string {
  if (!user) {
    // Fall back to a neutral subtitle when no user payload is available.
    return 'No identity payload available.';
  }

  // Return the resolved role and provider for the sidebar summary.
  return `${user.email} · ${buildRoleLabel(user.role)} · ${user.provider}`;
}

export {
  buildRoleCapabilityItems,
  buildRoleLabel,
  buildShellPageTitle,
  buildUserHeadline,
  buildUserSubtitle,
  canAccessRole,
  exchangeGoogleAuthCodeOnce,
  getNavLinkClassName,
  reviewerRoles,
};
