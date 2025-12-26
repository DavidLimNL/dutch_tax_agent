# Quick Reference: HITL Commands

## Essential Commands

### Start a New Session
```bash
uv run dutch-tax-agent ingest -i <directory> --year <year>
```
Example:
```bash
uv run dutch-tax-agent ingest -i ~/my_tax_docs --year 2024
```
Output includes session ID (e.g., `tax2024-abc123def456`)

### Check Session Status
```bash
uv run dutch-tax-agent status -t <session-id>
```

### Add More Documents
```bash
uv run dutch-tax-agent ingest -i <directory> -t <session-id>
```

### Calculate Taxes
```bash
uv run dutch-tax-agent calculate -t <session-id>
```

### Remove Documents
```bash
# By document ID
uv run dutch-tax-agent remove -t <session-id> --doc-id <id>

# By filename
uv run dutch-tax-agent remove -t <session-id> --filename <name>

# Remove all
uv run dutch-tax-agent remove -t <session-id> --all
```

### List All Sessions
```bash
uv run dutch-tax-agent sessions
```

### Delete a Session
```bash
uv run dutch-tax-agent reset -t <session-id>
```

## Common Workflows

### Simple Workflow
```bash
# 1. Process documents
uv run dutch-tax-agent ingest -i ~/docs --year 2024

# 2. Calculate (copy session ID from step 1)
uv run dutch-tax-agent calculate -t tax2024-abc123
```

### Iterative Workflow
```bash
# 1. Initial docs
uv run dutch-tax-agent ingest -i ~/docs --year 2024
# Session: tax2024-abc123

# 2. Check status
uv run dutch-tax-agent status -t tax2024-abc123

# 3. Add more docs
uv run dutch-tax-agent ingest -i ~/more_docs -t tax2024-abc123

# 4. Remove wrong doc
uv run dutch-tax-agent remove -t tax2024-abc123 --filename wrong.pdf

# 5. Calculate
uv run dutch-tax-agent calculate -t tax2024-abc123
```

### Review All Sessions
```bash
# List sessions
uv run dutch-tax-agent sessions

# Check each one
uv run dutch-tax-agent status -t <session-id>

# Calculate when ready
uv run dutch-tax-agent calculate -t <session-id>
```

## Tips

- **Save your session ID**: Write it down or save to a file
- **Check status often**: Use `status` to review extracted data
- **Documents are deduplicated**: Safe to re-run `ingest` on same folder
- **Remove before recalculate**: Can't remove after calculation completes
- **Sessions persist**: Can stop and restart the application

## Storage Locations

- **Checkpoints**: `~/.dutch_tax_agent/checkpoints.db`
- **Sessions**: `~/.dutch_tax_agent/sessions.json`

To reset everything:
```bash
rm -rf ~/.dutch_tax_agent/
```

