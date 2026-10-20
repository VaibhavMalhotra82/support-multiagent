# Setup and Deployment Guide

## Quick Start (Local Development)

### 1. Install Dependencies

```bash
# Create a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Initialize Database and Seed Data

```bash
# Create SQLite database and seed with default users/roles/permissions
python seed_db.py
```

This creates:
- **Roles**: admin, support, user
- **Permissions**: query_support, manage_rca, submit_feedback
- **Default Users**:
  - `admin` / `admin123` (admin role)
  - `support` / `support123` (support role)
  - `user` / `user123` (user role)

### 3. Run the API Server

```bash
# Start the FastAPI server with auto-reload
uvicorn app.main:app --reload

# Or explicitly bind to a port
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.

### 4. Test the API

Use the example client script:

```bash
python client_example.py
```

Or use `curl`:

```bash
# 1. Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "support", "password": "support123"}'

# 2. Query Support (use the token from login response)
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I fix a database error?", "metadata": {"product": "MyApp"}}'
```

---

## Docker Deployment

### Using Docker Compose (with Redis)

```bash
# Build and start services
docker-compose up --build

# Seed the database (in a separate terminal)
docker-compose exec api python seed_db.py
```

### Manual Docker Build

```bash
# Build the image
docker build -t support-multiagent:latest .

# Run with local Redis
docker run -p 8000:8000 \
  --network host \
  -e REDIS_HOST=127.0.0.1 \
  support-multiagent:latest
```

---

## Environment Configuration

Edit `.env` to configure:

```env
# Redis
REDIS_HOST=redis          # or localhost for local dev
REDIS_PORT=6379
REDIS_DB=0

# LLM (OpenAI)
OPENAI_API_KEY=sk-...     # Get from https://platform.openai.com
LLM_MODEL=gpt-4
LLM_TEMPERATURE=0.7

# LangSmith Observability
LANGSMITH_ENABLED=false   # Set to true to enable
LANGSMITH_API_KEY=...     # Get from https://smith.langchain.com
LANGSMITH_PROJECT=support-multiagent

# Vector Store
VECTOR_STORE_TYPE=chroma  # Options: chroma, weaviate, pinecone
CHROMA_PATH=./chroma_db
```

## Document ingestion

The admin ingestion endpoints accept local UTF-8 text paths and `http://` or `https://` URLs. HTML content is parsed as text and script, style, and noscript blocks are removed. Sources are chunked and stored in Chroma; the default chunk size is 1,000 characters with 150 characters of overlap.

PDF, DOCX, XLSX, images, binary files, directories, FTP, and other URL schemes are not parsed by the current adapter. Convert these sources to UTF-8 text or add a format-specific adapter before ingestion.

---

## LLM Integration

### Configure OpenAI (GPT-4)

1. Get API key from [OpenAI Platform](https://platform.openai.com/account/api-keys)
2. Add to `.env`: `OPENAI_API_KEY=sk-...`
3. Update `app/workflow/agents.py` to initialize LLM:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4",
    temperature=float(settings.llm_temperature),
    api_key=settings.openai_api_key,
)

# Pass to workflow
support_workflow = create_support_workflow(llm=llm)
```

### Other LLM Providers

- **Anthropic Claude**: `from langchain_anthropic import ChatAnthropic`
- **Open Source (Ollama)**: `from langchain_ollama import ChatOllama`
- **Local (LLaMA)**: `from langchain_community.llms import LlamaCpp`

---

## Vector Store Setup

### Chroma (Default)

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings()
vector_store = Chroma(
    collection_name="support_docs",
    embedding_function=embeddings,
    persist_directory="./chroma_db",
)
```

### Pinecone

```python
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings

index = pinecone.Index("support-docs")
vector_store = PineconeVectorStore(index, embeddings)
```

---

## LangSmith Integration

### Enable Observability

1. Sign up at [LangSmith](https://smith.langchain.com)
2. Create a project called "support-multiagent"
3. Get your API key
4. Add to `.env`:

```env
LANGSMITH_ENABLED=true
LANGSMITH_API_KEY=your-key-here
LANGSMITH_PROJECT=support-multiagent
```

5. Traces will automatically appear in LangSmith dashboard

### Create Datasets for Evaluation

```python
from langsmith import Client

client = Client()
dataset = client.create_dataset(
    dataset_name="support_evals",
    description="Support queries for evaluation",
)

# Add examples
for question, expected_answer in eval_data:
    client.create_example(
        dataset_id=dataset.id,
        inputs={"question": question},
        outputs={"answer": expected_answer},
    )
```

---

## Production Deployment

### Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: support-multiagent
spec:
  containers:
  - name: api
    image: support-multiagent:latest
    ports:
    - containerPort: 8000
    env:
    - name: REDIS_HOST
      value: redis-service
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: llm-secrets
          key: openai-key
    - name: LANGSMITH_API_KEY
      valueFrom:
        secretKeyRef:
          name: observability-secrets
          key: langsmith-key
```

### Environment Variables (Production)

Use secrets manager (AWS Secrets, HashiCorp Vault, etc.):

```bash
export OPENAI_API_KEY=sk-...
export LANGSMITH_API_KEY=...
export DATABASE_URL=postgresql://...  # Use PostgreSQL instead of SQLite
export REDIS_HOST=redis.internal
```

### Scaling Considerations

- **API**: Stateless, can scale horizontally
- **Redis**: Shared cache, one instance or cluster
- **Database**: SQLite suitable for small deployments; upgrade to PostgreSQL for production
- **Vector Store**: Use managed service (Pinecone, Weaviate Cloud)

---

## Monitoring and Observability

### Logs

The application logs to stdout. Use `docker logs` or container logging service:

```bash
docker logs support-multiagent | grep request_id
```

### Metrics

- TTFT (Time to First Token)
- Retrieval quality (precision, recall, NDCG)
- Confidence score accuracy
- Escalation rate
- Cache hit rate

Export metrics to Prometheus/DataDog/New Relic using standard libraries.

### Alerts

Set up alerts for:
- High escalation rate (>20%)
- Low confidence scores (<0.6)
- Response time SLA violations
- Cache miss spike

---

## Troubleshooting

### Issue: "LLM not configured"

**Solution**: Set `OPENAI_API_KEY` in `.env` and import/initialize in `app/workflow/agents.py`

### Issue: "Connection refused: redis"

**Solution**: Start Redis (`docker run redis:7.2`) or configure `REDIS_HOST=localhost`

### Issue: "Database is locked"

**Solution**: SQLite has concurrency limitations. Upgrade to PostgreSQL for production.

### Issue: "Retrieval returns no documents"

**Solution**:
1. Ensure vector store is populated with documents
2. Check metadata filters aren't too restrictive
3. Verify embeddings model is initialized

---

## API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

Endpoints:
- `POST /auth/login` — Authenticate user
- `POST /query` — Submit support query
- `POST /rca` — Create RCA record
- `POST /feedback` — Submit feedback

See `app/contracts/schemas.py` for request/response models.
