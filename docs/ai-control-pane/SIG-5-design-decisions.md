# SIG-5: Settings UI — design decisions and review evidence

**Linear:** SIG-5 (Settings / integrations setup)  
**Scope:** `frontend/src/App.tsx` — Settings route (`/settings`, legacy `/integrations` alias), provider connect forms

## Goals

- Give operators a single, scannable place to verify GitHub, Linear, Jira, and Cursor Cloud Agents configuration before launching work.
- Improve accessibility and responsiveness of the setup flow (labels, `aria-describedby`, live regions for save outcomes).
- Preserve **issue traceability** from intake through implementation: ticket identifiers and provider metadata stay visible in downstream surfaces (dashboard, task detail, runs).

## References (external)

- [Understanding WCAG 2.1 — Labels or Instructions (3.3.2)](https://www.w3.org/WAI/WCAG21/Understanding/labels-or-instructions.html) — clear setup instructions next to controls.
- [Understanding WCAG 2.1 — Error Identification (3.3.1)](https://www.w3.org/WAI/WCAG21/Understanding/error-identification.html) — errors announced in context.
- [Understanding WCAG 2.1 — Status Messages (4.1.3)](https://www.w3.org/WAI/WCAG21/Understanding/status-messages.html) — `role="status"` / `aria-live` for async success and failure messages.

## Implementation summary

| Area | Change | Rationale |
| --- | --- | --- |
| Settings layout | Hero panel, anchor nav to section IDs, grouped panels for each provider | Faster verification of each integration without long vertical scroll alone |
| Forms | Step copy + traceability notes wired through `aria-describedby`; password fields for secrets | Reduces guesswork; assistive tech gets setup context and relationship to audit expectations |
| Feedback | `aria-live="polite"` region for connect success and error strings | Reviewers and operators hear or see outcomes without hunting for toasts |
| Navigation | `getNavLinkClassName` treats `/integrations` as active for Settings | Legacy deep links keep wayfinding consistent |

## Manual checks performed for review evidence

- Keyboard: Tab through Settings anchor links → each section target receives focus via in-page navigation; form fields remain in logical order within each panel.
- Screen reader cues: each connect form exposes combined descriptions (help + a11y + traceability) through `aria-describedby`.
- Responsive: provider cards and form grids use existing breakpoints from the SIG-7 shell so narrow viewports stack without horizontal overflow on typical phone widths.

Automated tooling (axe, Lighthouse) is optional for reviewers; run locally against `npm run dev` on `/settings` if desired.

## Traceability

- Commits for this work use **SIG-5** in the message subject where possible for Linear ticket alignment.
- This document is the durable **review evidence** attachment for the Done state of SIG-5.
