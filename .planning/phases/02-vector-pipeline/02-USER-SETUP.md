# Phase 2: User Setup Required

**Generated:** 2026-01-21
**Phase:** 02-vector-pipeline
**Status:** Incomplete

## Environment Variables

| Status | Variable | Source | Add to |
|--------|----------|--------|--------|
| [ ] | `DATABRICKS_HOST` | Databricks workspace URL (e.g., https://xxx.cloud.databricks.com) | `.env` or shell |
| [ ] | `DATABRICKS_TOKEN` | Databricks -> User Settings -> Developer -> Access tokens -> Generate new token | `.env` or shell |

## Account Setup

- [ ] **Databricks access required**
  - Purpose: Embedding generation via GTE-large-en model serving
  - Ensure you have access to a Databricks workspace with Foundation Model APIs enabled

## How to Get Credentials

### DATABRICKS_HOST

1. Log in to your Databricks workspace
2. Copy the URL from the browser address bar
3. Format: `https://xxx.cloud.databricks.com` (include https://, no trailing slash)

### DATABRICKS_TOKEN

1. Log in to Databricks workspace
2. Click your username (top right) -> User Settings
3. Go to "Developer" tab
4. Click "Manage" next to Access tokens
5. Click "Generate new token"
6. Give it a descriptive name (e.g., "mnemo-embeddings")
7. Set expiration as appropriate
8. Copy the token (only shown once!)

## Verification

After setting the environment variables, verify setup:

```bash
# Test that credentials are set
python -c "from mnemo.embeddings import EmbeddingConfig; c = EmbeddingConfig.from_env(); print(f'Host: {c.host[:20]}...'); print(f'Token: {c.token[:10]}...')"

# Test actual API call (requires valid credentials)
python -c "
from mnemo.embeddings import DatabricksEmbedder
e = DatabricksEmbedder()
result = e.embed_one('Test embedding')
print(f'Embedding dimension: {len(result)}')
print('Success!')
"
```

Expected output:
```
Host: https://xxx.cloud...
Token: dapixxxxxx...
Embedding dimension: 1024
Success!
```

---
**Once all items complete:** Mark status as "Complete"
