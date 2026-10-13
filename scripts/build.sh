#!/bin/bash
set -euo pipefail

example=$1
image=$2
builder=${BUILDER:-paketobuildpacks/builder-noble-java-tiny:latest}
platform=${PLATFORM:-$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')}
artifacts="results/$example/build-artifacts"
mkdir -p "$artifacts"
auth_directory=$(mktemp -d "${TMPDIR:-/tmp}/aot-buildpacks-auth.XXXXXX")
trap 'rm -rf "$auth_directory"' EXIT
python3 scripts/docker_auth.py "$auth_directory" "$builder"
started=$(date +%s)
status=0
printf 'Building %s with %s for %s\n' "$example" "$builder" "$platform"
docker compose -f "examples/$example/compose.yaml" --profile tools run --rm --no-deps \
  --volume "$auth_directory:/pack-docker-config:ro" --env DOCKER_CONFIG=/pack-docker-config pack \
  build "$image" --path "/workspace/examples/$example" --builder "$builder" \
  --env-file "/workspace/examples/$example/buildpack.env" --platform "$platform" \
  --pull-policy if-not-present 2>&1 | tee "$artifacts/build.log" || status=$?
python3 - "$artifacts/build.json" "$image" "$builder" "$platform" "$started" "$status" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
output, image, builder, platform, started, status = sys.argv[1:]
Path(output).write_text(json.dumps({
    'image': image, 'builder': builder, 'platform': platform,
    'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': time.time() - int(started), 'exit_code': int(status),
    'scope': 'Complete pack build including downloads, Gradle tests, cache training or native compilation, and image export; caches may be reused'
}, indent=2) + '\n')
PY
if [ "$status" -ne 0 ]; then
  printf 'Build failed. See %s/build.log\n' "$artifacts" >&2
  exit "$status"
fi
printf 'Built %s. Evidence: %s\n' "$image" "$artifacts"
