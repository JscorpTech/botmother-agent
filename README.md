# Botmother Flow Agent

LangGraph-based conversational agent that generates valid flow JSON for the Botmother engine.

## Setup

```bash
pip install -r requirements.txt
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=sk-...
```

## CLI Usage

```bash
python -m botmother_agent.cli
```

## API Server

```bash
uvicorn botmother_agent.api:app --reload --port 8000
```

Swagger docs: http://localhost:8000/docs

### API Endpoints

#### Session-based (multi-turn conversation)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/sessions` | Create new session |
| `GET` | `/sessions/{id}` | Get session info |
| `POST` | `/sessions/{id}/chat` | Send message, get reply |
| `GET` | `/sessions/{id}/flow` | Get generated flow JSON |
| `POST` | `/sessions/{id}/flow/save` | Save flow to file |
| `GET` | `/sessions/{id}/history` | Get chat history |
| `POST` | `/sessions/{id}/reset` | Reset conversation |
| `DELETE` | `/sessions/{id}` | Delete session |

#### One-shot (single request)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/generate` | Describe bot → get flow JSON |
| `GET` | `/health` | Health check |

### Examples

**Create session and chat:**
```bash
# 1. Create session
curl -X POST http://localhost:8000/sessions

# 2. Chat (use session_id from step 1)
curl -X POST http://localhost:8000/sessions/{session_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Men /start komandasi bilan ishlaydigan oddiy bot yaratmoqchiman"}'

# 3. Get flow
curl http://localhost:8000/sessions/{session_id}/flow
```

**One-shot generation:**
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"description": "/start komandasi bilan salomlashuvchi va ismini so'\''raydigan bot"}'
```
