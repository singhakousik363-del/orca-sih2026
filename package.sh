#!/usr/bin/env bash
# Package the prototype, but only after proving the archive itself is sound.
#
# Twice now the working copy has been correct while the archive shipped older
# code, because a fix landed after the zip was built and the zip was never
# rebuilt. The user then reported a bug that no longer existed here, and time
# went into chasing it. So: verify, build, unpack, verify again, and compare.
set -euo pipefail

OUT=/mnt/user-data/outputs/orca-prototype.zip

echo "=== 1. verify the working copy ==="
python3 verify.py

echo
echo "=== 2. build ==="
rm -rf app/__pycache__ __pycache__
rm -f "$OUT"
TMP=$(mktemp -d)
cp -r . "$TMP/orca"
( cd "$TMP" && find orca -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  zip -qr "$OUT" orca -x "*__pycache__*" "*.pyc" )

echo "=== 3. verify the archive, not the working copy ==="
CHECK=$(mktemp -d)
( cd "$CHECK" && unzip -qo "$OUT" && cd orca && python3 verify.py )

echo
echo "=== 4. do they match? ==="
DIFF=$(diff -r --exclude=__pycache__ --exclude='*.pyc' . "$CHECK/orca" || true)
if [ -n "$DIFF" ]; then
  echo "ARCHIVE DIFFERS FROM THE WORKING COPY:"
  echo "$DIFF"
  rm -rf "$TMP" "$CHECK"
  exit 1
fi
echo "  archive matches the working copy exactly"

rm -rf "$TMP" "$CHECK"
echo
echo "packaged: $(unzip -l "$OUT" | tail -1)"
