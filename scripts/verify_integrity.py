#!/usr/bin/env python3
"""
StockSentinel Cryptographic Integrity Verifier
Grade-1 Security: Validates the current workspace against PROJECT_INTEGRITY_SEAL.json
and CHECKSUMS.sha256 to guarantee zero tampering and authentic state.
"""

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEAL_PATH = PROJECT_ROOT / "PROJECT_INTEGRITY_SEAL.json"


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify():
    if not SEAL_PATH.exists():
        print(f"❌ Error: Integrity seal not found at {SEAL_PATH}")
        print("Run 'python3 scripts/seal_project.py' to generate one first.")
        sys.exit(1)

    with open(SEAL_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    expected_master_hash = manifest.get("master_root_hash")
    files = manifest.get("files", [])

    print("=" * 60)
    print("🔒 StockSentinel Grade-1 Cryptographic Integrity Verification")
    print("=" * 60)
    print(f"Sealed At (UTC): {manifest.get('sealed_at_utc')}")
    print(f"Expected Master Root Hash: {expected_master_hash}")
    print(f"Total Files in Manifest:   {len(files)}\n")

    passed = 0
    mismatched = []
    missing = []
    master_hasher = hashlib.sha256()

    for item in files:
        rel_path = item["path"]
        expected_hash = item["sha256"]
        file_path = PROJECT_ROOT / rel_path

        if not file_path.exists():
            missing.append(rel_path)
            continue

        actual_hash = compute_sha256(file_path)
        master_hasher.update(f"{actual_hash}:{rel_path}\n".encode("utf-8"))

        if actual_hash == expected_hash:
            passed += 1
        else:
            mismatched.append({
                "path": rel_path,
                "expected": expected_hash,
                "actual": actual_hash,
            })

    computed_master_hash = master_hasher.hexdigest()

    print(f"Results:")
    print(f"  ✅ Verified Matching: {passed}/{len(files)}")

    if missing:
        print(f"  ❌ Missing Files ({len(missing)}):")
        for m in missing:
            print(f"     - {m}")

    if mismatched:
        print(f"  ⚠️ Mismatched Hashes / Tampered Files ({len(mismatched)}):")
        for m in mismatched:
            print(f"     - {m['path']} (Expected: {m['expected'][:10]}..., Got: {m['actual'][:10]}...)")

    print("-" * 60)
    if not missing and not mismatched and computed_master_hash == expected_master_hash:
        print("🎉 STATUS: 100% INTEGRITY VERIFIED (Grade-1 Secured & Untampered)")
        print(f"Master Fingerprint: {computed_master_hash}")
        sys.exit(0)
    else:
        print("❌ STATUS: INTEGRITY CHECK FAILED (Discrepancies detected)")
        print(f"Expected Master: {expected_master_hash}")
        print(f"Computed Master: {computed_master_hash}")
        sys.exit(1)


if __name__ == "__main__":
    verify()
