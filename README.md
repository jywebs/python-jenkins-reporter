# Jenkins Top Jobs Reporter (python-jenkins)

Generates a CSV ranking Jenkins jobs by build count and runtime across one or more controllers.  
Uses `python-jenkins` (official library) and Basic Auth with username + API token.

## Features
- Multiple controllers (comma separated)
- Time window filter (last N days)
- Ranks by: build count, total runtime, average runtime, longest runtime
- CSV output for spreadsheets and BI tools
- Optional JSON output
- Safe pagination limits to avoid large payloads

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install python-jenkins requests pandas
```

## Usage
```bash
python jenkins_top_jobs_pyjenkins.py \
  --controllers https://jenkins-a.example.com,https://jenkins-b.example.com \
  --user "$JENKINS_USER" \
  --token "$JENKINS_API_TOKEN" \
  --days 30 \
  --max-builds 200 \
  --top 25 \
  --out top_jobs.csv \
  --json top_jobs.json
```

Environment variables are optional. Flags override env vars.

```bash
export JENKINS_USER=your-user
export JENKINS_API_TOKEN=your-token
```

## Output columns (CSV and JSON)

- controller
- job_name
- job_url
- builds
- failures
- failure_rate
- total_runtime_seconds
- avg_runtime_seconds
- longest_runtime_seconds