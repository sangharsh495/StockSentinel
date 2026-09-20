#!/usr/bin/env python3
"""
StockSentinel Cryptographic Integrity Sealer & Manifest Generator
Grade-1 Security: Generates SHA-256 hashes for all project source files,
creates CHECKSUMS.sha256 and PROJECT_INTEGRITY_SEAL.json with a Master Root Hash.
"""

import os
import sys
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories and patterns to exclude from seal (ephemeral, local or ignored)
EXCLUDE_DIRS = {
    ".git",
    ".gradle",
    "build",
    "venv",
    ".venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "captures",
    "intermediates",
    "outputs",
}

EXCLUDE_FILES = {
    ".DS_Store",
    ".env",
    "local.properties",
    "PROJECT_INTEGRITY_SEAL.json",
    "CHECKSUMS.sha256",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".class",
    ".apk",
    ".aab",
    ".log",
    ".tmp",
    ".iml",
    ".keystore",
    ".jks",
}


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def should_include_file(path: Path) -> bool:
    """Determine if a file should be sealed in the integrity manifest."""
    rel = path.relative_to(PROJECT_ROOT)
    parts = set(rel.parts)

    # Check excluded directory names
    if any(ex in parts for ex in EXCLUDE_DIRS):
        return False

    # Check filename
    if path.name in EXCLUDE_FILES or path.name.startswith("._"):
        return False

    # Check extension
    if path.suffix in EXCLUDE_EXTENSIONS:
        return False

    return True


def seal_project():
    print(f"🔒 Sealing StockSentinel project at: {PROJECT_ROOT}")

    file_records = []
    sha256_lines = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in sorted(files):
            file_path = Path(root) / file
            if should_include_file(file_path):
                rel_path = file_path.relative_to(PROJECT_ROOT).as_posix()
                file_hash = compute_sha256(file_path)
                file_size = file_path.stat().st_size

                file_records.append({
                    "path": rel_path,
                    "sha256": file_hash,
                    "size_bytes": file_size,
                })
                sha256_lines.append(f"{file_hash}  {rel_path}\n")

    # Sort deterministically by relative path
    file_records.sort(key=lambda x: x["path"])
    sha256_lines.sort(key=lambda x: x.split("  ")[1])

    # Compute Master Root Hash (hash of all sorted hashes concatenated)
    master_hasher = hashlib.sha256()
    for record in file_records:
        master_hasher.update(f"{record['sha256']}:{record['path']}\n".encode("utf-8"))
    master_root_hash = master_hasher.hexdigest()

    timestamp_iso = datetime.now(timezone.utc).isoformat()

    manifest_data = {
        "project": "StockSentinel",
        "description": "Cryptographically Sealed Project Manifest & Source Integrity Record",
        "security_grade": "Grade-1 (Cryptographic SHA-256 Sealed)",
        "sealed_at_utc": timestamp_iso,
        "master_root_hash": master_root_hash,
        "total_sealed_files": len(file_records),
        "files": file_records,
    }

    # Write PROJECT_INTEGRITY_SEAL.json
    manifest_path = PROJECT_ROOT / "PROJECT_INTEGRITY_SEAL.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # Write CHECKSUMS.sha256 (standard UNIX sha256sum format)
    checksums_path = PROJECT_ROOT / "CHECKSUMS.sha256"
    with open(checksums_path, "w", encoding="utf-8") as f:
        f.writelines(sha256_lines)

    print(f"✅ Project successfully sealed!")
    print(f"   Total Files Sealed: {len(file_records)}")
    print(f"   Master Root Hash:   {master_root_hash}")
    print(f"   Manifest File:      {manifest_path.name}")
    print(f"   Checksums File:     {checksums_path.name}")

    return master_root_hash, len(file_records)


if __name__ == "__main__":
    seal_project()
