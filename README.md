# Percus Physical AI Interfaces

User interfaces for the Percus Physical AI Framework.

**Owner:** Percus AI (fork source for customers)

## Structure

```
physical-ai-interfaces/
├── backend/              # Python FastAPI (all logic)
├── cli/                  # Python httpx client
├── web/                  # TypeScript React
└── tauri/                # Rust + Web (desktop app)
```

## Architecture

All clients connect to the Backend via REST API.
Backend URL is configurable (local or remote).

```
         CLI ──────┐
                   │
         Web ──────┼────▶ Backend (FastAPI)
                   │
         Tauri ────┘
```

## Usage

### Start Backend
```bash
cd backend
uv sync
percus-server --port 8000
```

### Use CLI
```bash
cd cli
uv sync
export PERCUS_BACKEND_URL=http://localhost:8000
percus projects
```

### Use Web
```bash
cd web
npm install
npm run dev
# Configure backend URL in browser settings
```

### Use Tauri
```bash
cd tauri
npm install
npm run tauri dev
# Backend starts automatically as sidecar
```

## License

Proprietary - Percus AI Inc.

Customers may fork this repository.
