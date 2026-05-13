#!/usr/bin/env python3
"""Generate activation codes for 照片日记."""
import json, secrets, string, sys
from pathlib import Path

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
OUT = Path(__file__).parent / "codes.json"

# Merge with existing codes
existing = {}
if OUT.exists():
    existing = json.loads(OUT.read_text())

new_codes = {}
for _ in range(COUNT):
    # Format: XXXX-XXXX-XXXX (12 alphanumeric chars)
    raw = secrets.token_hex(6).upper()  # 12 hex chars
    code = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"
    new_codes[code] = {"used": False, "created": ""}

all_codes = {**existing, **new_codes}
OUT.write_text(json.dumps(all_codes, ensure_ascii=False, indent=2))
print(f"Generated {len(new_codes)} new codes. Total: {len(all_codes)}. Saved to {OUT}")

# Print new codes for copy-paste into 面包多
print("\n--- Copy below into 面包多 card list ---")
for code in sorted(new_codes.keys()):
    print(code)
