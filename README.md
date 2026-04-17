# AI Control Pane    

Scaffolded product demo for an AI-assisted engineering control pane with:
- `frontend`: Vite + React + TypeScript UI
- `backend`: FastAPI integration layer

## Frontend
```powershell
cd frontend
npm install
npm run dev
```

Optional environment override:
```powershell
Copy-Item .env.example .env
```

## Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Optional backend integration configuration:
```powershell
Copy-Item .env.example .env
```

## Hybrid Integrations
The app implements the recommended day-one stack from the integration spec:
- `GitHub` for repositories and pull-request context
- `GitHub Actions` for CI status context
- `Linear` for issue intake
- `Repo markdown` for knowledge source attachment
- `Google SSO-style identity abstraction` for approval attribution

The integration layer runs in `hybrid` mode:
- When provider environment variables are configured, the backend attempts live provider calls.
- When credentials or provider configuration are missing, the app falls back to safe in-memory demo data.
- Repo markdown docs are discovered locally from `docs/` and `README.md`.

## Backend Environment Variables
`backend/.env.example` documents the supported integration variables:
- `GITHUB_TOKEN`
- `GITHUB_OWNER`
- `GITHUB_REPOSITORIES`
- `LINEAR_API_KEY`
- `LINEAR_TEAM_ID`
- `CONTROL_PANE_DOCS_DIR`
- `CONTROL_PANE_DEFAULT_USER_NAME`
- `CONTROL_PANE_DEFAULT_USER_EMAIL`
- `CONTROL_PANE_DEFAULT_USER_ROLE`
- `CONTROL_PANE_FRONTEND_URL`
- `CONTROL_PANE_SESSION_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_HOSTED_DOMAIN`
- `GOOGLE_ALLOWED_DOMAINS`
- `GOOGLE_ADMIN_EMAILS`
- `GOOGLE_ADMIN_DOMAINS`
- `GOOGLE_TECH_LEAD_EMAILS`
- `GOOGLE_TECH_LEAD_DOMAINS`
- `GOOGLE_ENGINEER_EMAILS`
- `GOOGLE_ENGINEER_DOMAINS`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`

## Work Intake Enrichment
The Work Intake page exposes an **Enrich** button underneath the Task title, Prompt, and Acceptance criteria textboxes. Each button calls `POST /api/intake/enrich`, which uses `OPENAI_API_KEY` plus the markdown files under `docs/` (and the repo `README.md`) to refine the targeted field in-place. Set `OPENAI_MODEL` to override the default model (`gpt-4o-mini`) and `OPENAI_BASE_URL` to point at a compatible endpoint.

## Google SSO
When `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` are configured, the sign-in screen switches to a Google OAuth flow:
- the browser starts at `GET /api/auth/google/start`
- Google redirects back to `GET /api/auth/google/callback`
- the frontend exchanges the short-lived callback code at `POST /api/auth/google/exchange`

Role access is assigned on the backend from the configured email and domain rules with precedence `admin` > `tech_lead` > `engineer`. App sessions now use a signed bearer token so identity survives across backend invocations; set `CONTROL_PANE_SESSION_SECRET` in deployed environments if you do not want to fall back to `GOOGLE_CLIENT_SECRET`. When Google SSO is not configured, the original guided local sign-in remains available as a fallback.

## Integration API Surface
The backend now exposes the integration-oriented endpoints from the product spec:
- `GET /api/dashboard`
- `GET /api/runs/:id`
- `GET /api/approvals`
- `GET /api/policies/:scope`
- `GET /api/intake`
- `GET /api/integrations`
- `GET /api/me`
- `POST /api/tasks`
- `POST /api/runs`
- `POST /api/approvals`
- `POST /api/intake/enrich`

## Current Scope
- Data-backed product shell with live-or-fallback provider integrations served by FastAPI
- Dashboard, work intake, task detail, approval inbox, policy center, and integrations management
- Hybrid integration support for GitHub, GitHub Actions, Linear, repo markdown, and identity attribution
