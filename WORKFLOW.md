# LangGraph Multi-Agent Workflow Documentation

## Overview

The support system uses **LangGraph** to orchestrate multiple specialized agents through a directed acyclic graph (DAG). Each agent is responsible for a specific task in the support workflow.

## Workflow Architecture

```
Request Input
    ↓
[1] classify_intent ────→ Determine query type (troubleshooting, known_issue, policy, etc.)
    ↓
[2] retrieve_documents ─→ Hybrid search (sparse + dense) + metadata filtering
    ↓
[3] generate_answer ────→ LLM-based answer generation using retrieved context
    ↓
[4] score_confidence ───→ Confidence scoring (retrieval + generation quality)
    ↓
[5] analyze_root_cause ─→ Deep-dive RCA if confidence is sufficient
    ↓
[6] decide_escalation ──→ Determine if human escalation is needed
    ↓
[7] persist_response ───→ Store conversation, RCA, and feedback
    ↓
Response Output
```

## Agent Descriptions

### 1. Classify Intent
**Purpose**: Categorize the user's query to route to appropriate handlers.

**Input**: User question
**Output**: Intent classification + confidence score
**Thresholds**: None (always executes)

**Possible Intents**:
- `troubleshooting` - General troubleshooting requests
- `known_issue` - Known issues or bugs
- `policy` - Policy or configuration questions
- `escalation` - Requests needing immediate escalation
- `other` - Unclassified

---

### 2. Retrieve Documents
**Purpose**: Fetch relevant knowledge base documents using hybrid retrieval.

**Input**: Question, intent, metadata filters
**Output**: Ranked document list + retrieval confidence
**Features**:
- Sparse retrieval (keyword matching)
- Dense retrieval (embedding similarity)
- Metadata filtering (product, version, tier, etc.)
- Retrieval caching (300s TTL)

---

### 3. Generate Answer
**Purpose**: Create a comprehensive answer using retrieved documents.

**Input**: Question, retrieved documents
**Output**: Generated answer + source references
**Features**:
- LLM-based answer generation
- Source attribution
- Graceful fallback on errors

---

### 4. Score Confidence
**Purpose**: Quantify confidence in the generated answer.

**Input**: Question, answer, retrieval score
**Output**: Confidence score (0.0-1.0)
**Calculation**:
- Retrieval confidence: Average of document similarity scores
- Generation confidence: Model-based assessment
- Combined score: Weighted ensemble (default: 50/50 split)

---

### 5. Analyze Root Cause
**Purpose**: Identify root causes and resolutions for complex issues.

**Input**: Question, retrieved documents, conversation history
**Output**: Root cause + resolution recommendation
**Condition**: Only executes if confidence score > 0.6

**Output Format** (JSON):
```json
{
  "root_cause": "Connection pool exhaustion",
  "resolution": "Increase pool size and optimize queries"
}
```

---

### 6. Decide Escalation
**Purpose**: Determine if human support escalation is needed.

**Input**: Question, confidence score, conversation history
**Output**: Escalation decision + reason
**Thresholds**:
- Auto-escalate if confidence < 0.5
- Consider conversation history and query complexity
- Check for sensitivity flags or policy-related queries

**Output Format** (JSON):
```json
{
  "should_escalate": true,
  "reason": "Low confidence in automated response"
}
```

---

### 7. Persist Response
**Purpose**: Store conversation history, RCA records, and feedback.

**Input**: Complete workflow state
**Output**: None (side effects only)
**Actions**:
- Add turn to short-term conversation memory
- Add summary to long-term memory
- Store RCA record if confidence > 0.7
- Log event to observability system

---

## State Management

The workflow uses a single, immutable `SupportAgentState` dataclass that flows through all agents:

```python
@dataclass
class SupportAgentState:
    # Input
    question: str
    session_id: str
    user_id: Optional[int]
    tenant_id: Optional[str]
    metadata: Optional[Dict[str, Any]]

    # Agent outputs
    intent: Optional[str]
    retrieved_documents: List[Dict[str, Any]]
    answer: Optional[str]
    confidence_score: float
    root_cause: Optional[str]
    should_escalate: bool

    # Metadata
    request_id: Optional[str]
    created_at: str
    conversation_history: List[Dict[str, str]]
```

## Caching Strategy

### Retrieval Caching
- **Key**: SHA256 hash of (question, metadata)
- **TTL**: 300 seconds (configurable)
- **Layer**: In-memory (default) or Redis (distributed)

### Prompt Caching
- Built into agent nodes
- Reuses prompt templates for repeated query patterns

### Response Caching
- Final answers cached by session + question
- Used for repeated questions in same conversation

## LangSmith Integration

When `LANGSMITH_ENABLED=true`:
- All agent nodes are wrapped with `@traceable` decorator
- Traces include timing, tokens, and state transitions
- Datasets can be captured for evaluation
- Monitor real-time performance metrics

### Setup
1. Set `LANGSMITH_ENABLED=true` in `.env`
2. Add `LANGSMITH_API_KEY` (from LangSmith dashboard)
3. Optionally set `LANGSMITH_PROJECT` (default: "support-multiagent")

## Performance Considerations

### TTFT (Time to First Token)
- **Retrieval caching** reduces repeated queries to <100ms
- **Prompt caching** with Claude reduces latency by ~50%
- Parallel retrieval (sparse + dense) improves speed

### Confidence Scoring
- Uses log probabilities + semantic consistency checks
- Lightweight LLM call (smaller model can be used)
- Fallback to heuristics if LLM unavailable

### Memory Management
- Short-term: Last N turns in session (default: 5)
- Long-term: Compressed summaries + embeddings
- Automatic pruning on session expiry

## Evaluation and Feedback Loop

### Collection
- User feedback: helpful/not helpful + comment
- LLM confidence vs actual correctness
- Retrieval precision/recall metrics

### Offline Evaluation
1. Replay historical support transcripts
2. Compare automated answers vs human resolutions
3. Measure precision@k, recall, and NDCG for retrieval
4. Tune confidence thresholds based on false positive rate

### Continuous Improvement
- A/B test reranker models
- Adjust metadata filter weights
- Retrain confidence scorer on feedback
- Update prompt templates based on human corrections

## Error Handling

- **LLM unavailable**: Fall back to cached answers or escalate
- **Retrieval failure**: Return generic response and escalate
- **Parsing errors**: Retry with simpler format or escalate
- **Timeout**: Return partial state and escalate

## Future Enhancements

1. **Conditional routing**: Route to specialist agents based on intent
2. **Multi-turn conversations**: Maintain session state across multiple queries
3. **Active learning**: Flag uncertain predictions for human review
4. **A/B testing**: Compare retrieval and reranker strategies
5. **Cost optimization**: Use smaller models for simple queries
6. **Custom agents**: Domain-specific agents for specific products/services
