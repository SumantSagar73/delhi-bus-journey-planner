#!/usr/bin/env bash
# Resumable download of the October 2026 DTC bus GPS archive (16 GB).
# Restarts automatically if the connection stalls, and resumes where it stopped.
cd "$(dirname "$0")/data/raw" || exit 1
URL=https://pub-091bd9e794bb4877b10b29e6df80f065.r2.dev/2026-10/delhi-dtc-bus-gtfs-rt-2026-10.7z
F=delhi-dtc-bus-gtfs-rt-2026-10.7z
SIZE=16077236568
until [ "$(stat -c %s "$F" 2>/dev/null || echo 0)" -ge "$SIZE" ]; do
  curl -C - -sS --speed-limit 100000 --speed-time 30 -O "$URL" || sleep 3
done
echo DOWNLOAD_DONE
