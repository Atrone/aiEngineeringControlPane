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
- `GOOGLE_CLIENT_ID`

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

## Current Scope
- Data-backed product shell with live-or-fallback provider integrations served by FastAPI
- Dashboard, work intake, task detail, approval inbox, policy center, and integrations management
- Hybrid integration support for GitHub, GitHub Actions, Linear, repo markdown, and identity attribution
