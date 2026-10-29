# Windows setup notes

## Prerequisites

- Windows 10/11 with PowerShell
- Python 3.12+
- Node.js 20+ and npm
- Ollama for live local question generation and answer evaluation (optional when using mock mode)

## Install and configure

Run PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, allow it for the current terminal only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Install Ollama and download the default model:

```powershell
winget install --id Ollama.Ollama -e
ollama pull llama3.2
ollama list
```

The Ollama desktop app normally starts the local service. If it is not running, open a separate terminal and run `ollama serve`. Set `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in `.env` if using a different endpoint/model; pull the configured model with `ollama pull <model>`. After starting the API, verify connectivity and model presence at `http://localhost:8000/api/llm/status`.

For UI/API development without Ollama, set `MOCK_LLM=true` in `.env`. This mode returns deterministic fixtures and does not provide live model inference. Use `MOCK_LLM=false` for the Ollama service.

Structured question generation and answer evaluation pass a Pydantic JSON Schema to Ollama and retry malformed/schema-invalid responses up to three times. For local diagnostics, `DEBUG=true` enables raw response logging only on requests with no user-provided document or answer content; it is disabled by default.

## Run the application

Start the backend from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m uvicorn app.main:app --app-dir backend --reload
```

Start the frontend in a second terminal:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Swagger is at `http://localhost:8000/docs`; API health and Ollama/model status are at `http://localhost:8000/api/health` and `http://localhost:8000/api/llm/status`.

Resume and job-description analysis automatically indexes extracted text into local ChromaDB. The first indexing operation may download the configured Sentence Transformers embedding model. Document chunks are scoped to the current browser workspace and unchanged content is not re-embedded. Completed interview sessions can be downloaded as PDF reports from the report screen.

## Docker Compose (optional)

Start Docker Desktop and ensure the Linux engine is running before Compose commands. The default Compose backend expects Ollama on Windows at `host.docker.internal:11434`; install Ollama and pull the model on the host as described above.

```powershell
docker compose config --quiet
docker compose up --build -d
```

Alternatively, run Ollama as an optional Compose service:

```powershell
$env:DOCKER_OLLAMA_BASE_URL = "http://ollama:11434"
docker compose --profile ollama up --build -d
docker compose exec ollama ollama pull llama3.2
```

## Troubleshooting

- **Cannot reach Ollama:** Start the Ollama app or run `ollama serve`; check `OLLAMA_BASE_URL` and that the API can reach that host/port.
- **Model is missing:** Run `ollama pull <OLLAMA_MODEL>` and confirm with `ollama list`. The status endpoint reports a missing configured model.
- **Request times out:** Increase `OLLAMA_TIMEOUT_SECONDS` in `.env`, or try a smaller model; restart the backend after editing settings.
- **RAG dependencies unavailable:** Reinstall `backend\requirements.txt`. Allow network access for the first embedding model download; embedding and vector search run locally afterward.
- **RAG indexing fails:** Check the API error shown by the UI and ensure the backend can write to `CHROMA_PATH`. Retrying an unchanged document does not create duplicate vectors.
- **Frontend cannot reach API:** Run the backend on port 8000 and use the Vite development server; verify `http://localhost:8000/api/health`.
- **Compose cannot connect/build:** Start Docker Desktop's Linux engine and check `docker info`. Compose file validation alone does not establish that images can be built or containers can become healthy.

## Verification status

Verified on 2026-10-29: all backend tests passed, the frontend production build succeeded, and `docker compose config --quiet` passed. Live Ollama behavior is verified only when a configured model is installed and exercised successfully. Docker runtime/build verification requires a working Docker daemon.
