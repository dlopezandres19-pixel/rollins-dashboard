"""
Generates ai-brand-tracker/data/manifest.json
listing all weekly CSV files so the dashboard can load them without
needing a directory listing endpoint.

Run from the repo root. Add to the GitHub Actions workflow after
run_tracker.py completes:

    - name: Generate AI data manifest
      run: python ai-brand-tracker/src/generate_manifest.py
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

WEEKLY_DIR = Path(__file__).parent.parent / "data" / "weekly"
MANIFEST   = Path(__file__).parent.parent / "data" / "manifest.json"

def main():
    csv_files = sorted(
        f.name for f in WEEKLY_DIR.glob("*_brand_metrics.csv")
        if f.is_file()
    )
    manifest = {
        "weekly":       csv_files,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"manifest.json written — {len(csv_files)} weekly file(s):")
    for f in csv_files:
        print(f"  {f}")

if __name__ == "__main__":
    main()
