### Script: `jenkins_top_jobs_pyjenkins.py`

```python
#!/usr/bin/env python3
"""
Query one or more Jenkins controllers, gather job build stats, and rank top jobs.
Requires: python-jenkins, requests, pandas

Example:
  python jenkins_top_jobs_pyjenkins.py \
    --controllers https://jenkins-a.example.com,https://jenkins-b.example.com \
    --user $JENKINS_USER --token $JENKINS_API_TOKEN \
    --days 30 --max-builds 200 --top 25 --out top_jobs.csv --json top_jobs.json
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import jenkins
import requests
import pandas as pd


def within_window(ts_ms: int, since_dt):
    if not since_dt:
        return True
    # python-jenkins returns timestamps in ms like Jenkins REST
    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return ts >= since_dt


def fmt_seconds(sec: float) -> str:
    if not sec or sec <= 0:
        return "0s"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def collect_controller_jobs(jc: jenkins.Jenkins, controller_url: str, max_builds: int, since_dt):
    rows: List[Dict] = []

    # list_jobs gives limited info; get_all_jobs can be heavy on very large instances
    jobs = jc.get_all_jobs()  # respects folders and multibranch
    for idx, job in enumerate(jobs, 1):
        # polite pacing to avoid load spikes
        if idx % 50 == 0:
            time.sleep(0.3)

        name = job.get("fullname") or job.get("name")
        if not name:
            continue

        try:
            info = jc.get_job_info(name, fetch_all_builds=False)
        except jenkins.NotFoundException:
            continue
        except Exception:
            continue

        # Get recent builds for the job
        builds_meta = info.get("builds", [])[:max_builds]
        builds = []
        for b in builds_meta:
            try:
                binfo = jc.get_build_info(name, b["number"])
                if within_window(binfo.get("timestamp", 0), since_dt):
                    builds.append(binfo)
            except Exception:
                continue

        if not builds:
            continue

        count = len(builds)
        total_runtime = sum((b.get("duration") or 0) / 1000.0 for b in builds)  # ms to sec
        avg_runtime = total_runtime / count if count else 0.0
        longest = max(((b.get("duration") or 0) / 1000.0 for b in builds), default=0.0)
        failures = sum(
            1
            for b in builds
            if str(b.get("result")) not in ("SUCCESS", "ABORTED", "None")
        )

        # Try to construct a direct job URL
        job_url = info.get("url") or f"{controller_url.rstrip('/')}/job/{name.replace('/', '/job/')}"

        rows.append(
            {
                "controller": controller_url,
                "job_name": name,
                "job_url": job_url,
                "builds": count,
                "failures": failures,
                "failure_rate": round((failures / count) * 100, 2),
                "total_runtime_seconds": round(total_runtime, 2),
                "avg_runtime_seconds": round(avg_runtime, 2),
                "longest_runtime_seconds": round(longest, 2),
            }
        )

    return rows


def collect_stats(controllers, user, token, verify_tls, max_builds, days):
    since_dt = None
    if days and days > 0:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)

    all_rows: List[Dict] = []
    for base in controllers:
        base = base.rstrip("/")
        print(f"Scanning controller: {base}")
        # python-jenkins uses Basic Auth. TLS verify is at requests level.
        # If you have a custom CA, set REQUESTS_CA_BUNDLE env var.
        jc = jenkins.Jenkins(base, username=user, password=token)
        try:
            _ = jc.get_whoami()
        except Exception as e:
            print(f"  Unable to auth to {base}: {e}")
            continue

        try:
            rows = collect_controller_jobs(jc, base, max_builds, since_dt)
            print(f"  Jobs with builds in window: {len(rows)}")
            all_rows.extend(rows)
        except Exception as e:
            print(f"  Failed collecting from {base}: {e}")
            continue

    return all_rows


def main():
    ap = argparse.ArgumentParser(description="Rank Jenkins jobs by build count and runtime using python-jenkins.")
    ap.add_argument("--controllers", required=True, help="Comma separated Jenkins base URLs")
    ap.add_argument("--user", default=os.getenv("JENKINS_USER", ""), help="Jenkins username or env JENKINS_USER")
    ap.add_argument("--token", default=os.getenv("JENKINS_API_TOKEN", ""), help="Jenkins API token or env JENKINS_API_TOKEN")
    ap.add_argument("--verify-tls", action="store_true", help="Verify TLS certs. For custom CA set REQUESTS_CA_BUNDLE")
    ap.add_argument("--days", type=int, default=30, help="Only count builds from last N days (default 30)")
    ap.add_argument("--max-builds", type=int, default=200, help="Max builds to fetch per job (default 200)")
    ap.add_argument("--top", type=int, default=25, help="Top N to print to console (default 25)")
    ap.add_argument("--sort", choices=["builds", "total_runtime_seconds", "avg_runtime_seconds", "longest_runtime_seconds"],
                    default="builds", help="Sort key for top list")
    ap.add_argument("--out", default="top_jobs.csv", help="CSV output path")
    ap.add_argument("--json", default="", help="Optional JSON output path")
    args = ap.parse_args()

    controllers = [c.strip() for c in args.controllers.split(",") if c.strip()]
    if not controllers:
        print("No controllers provided.")
        return

    if not args.user or not args.token:
        print("Username and API token are required. Use flags or env vars JENKINS_USER and JENKINS_API_TOKEN.")
        return

    rows = collect_stats(
        controllers=controllers,
        user=args.user,
        token=args.token,
        verify_tls=args.verify_tls,
        max_builds=args.max_builds,
        days=args.days,
    )

    if not rows:
        print("No job data found in the selected window.")
        return

    df = pd.DataFrame(rows)

    # Sort and preview top N
    df_sorted = df.sort_values(by=args.sort, ascending=False)
    top_df = df_sorted.head(args.top).copy()

    def humanize(col):
        return [fmt_seconds(x) for x in col]

    top_preview = top_df[[
        "controller", "job_name", "builds", "failure_rate", "avg_runtime_seconds", "longest_runtime_seconds"
    ]].copy()
    top_preview.rename(columns={
        "avg_runtime_seconds": "avg_runtime_human",
        "longest_runtime_seconds": "longest_runtime_human"
    }, inplace=True)
    top_preview["avg_runtime_human"] = humanize(top_df["avg_runtime_seconds"])
    top_preview["longest_runtime_human"] = humanize(top_df["longest_runtime_seconds"])

    print("\nTop jobs preview:")
    print(top_preview.to_string(index=False))

    # Write CSV and optional JSON
    df_sorted.to_csv(args.out, index=False)
    print(f"\nWrote CSV: {args.out}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(df_sorted.to_dict(orient="records"), f, indent=2)
        print(f"Wrote JSON: {args.json}")


if __name__ == "__main__":
    main()