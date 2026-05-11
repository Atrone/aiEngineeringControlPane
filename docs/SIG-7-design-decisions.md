# SIG-7: Frontend revamp — design decisions

**Linear:** SIG-7 (Frontend Revamp)  
**Scope:** `frontend/` — Vite + React control pane UI

## Goals

- Improve responsiveness and density on smaller viewports without changing backend contracts or route structure.
- Align interaction patterns with common AI product consoles (clear hierarchy, persistent workspace chrome, focused content column).
- Strengthen accessibility semantics for loading, errors, and tabbed evidence.

## References (external)

- [WAI-ARIA Authoring Practices Guide — Tabs pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) — tablist, `aria-selected`, `aria-controls`, keyboard navigation.
- [Understanding WCAG 2.1 — Focus Visible (2.4.7)](https://www.w3.org/WAI/WCAG21/Understanding/focus-visible.html) — visible focus for keyboard users.
- [Understanding WCAG 2.1 — Bypass Blocks (2.4.1)](https://www.w3.org/WAI/WCAG21/Understanding/bypass-blocks.html) — skip link to main content.

## Implementation summary

| Area | Change | Rationale |
| --- | --- | --- |
| Shell layout | Mobile drawer sidebar with overlay + Menu toggle; Escape closes drawer | Avoids stacking a tall sidebar above content on phones; matches drawer navigation used across modern dashboards |
| Landmarks | Skip link to `#main-content`; `<main>` wraps routed content | Supports 2.4.1 and clearer screen reader page structure |
| Loading / errors | `role="status"` + `aria-busy` on loading; `role="alert"` on errors | Announces async state changes to assistive tech |
| Evidence panel | Tablist semantics + Arrow/Home/End on tab row | Keyboard parity and clearer relationships between tabs and panels |
| Visual system | Softer radial page background, refined panel tokens, auto-fit metric grid, max content width | Improves scanability and prevents ultra-wide line lengths on large monitors |

## Manual accessibility checks performed

- Tab order: skip link → Menu (mobile) → primary actions → page content; focus returns predictably after drawer close.
- Keyboard: evidence tabs respond to Left/Right/Home/End when focus is in the tablist.
- Zoom: layout remains usable at ~200% browser zoom on a 1280px-wide viewport (primary grids collapse to single column per existing breakpoints).

Automated tooling (axe, Lighthouse) was not added to the repo in this change; reviewers may run them locally against `npm run dev` if desired.

## Traceability

All commits for this work reference **SIG-7** in the message subject for Linear ticket traceability.
