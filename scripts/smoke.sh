#!/usr/bin/env bash
# Post-deploy smoke checks. Run against staging before promoting, and against
# production immediately after.
#
# Every check here is a thing that has a plausible way of being wrong *after* a
# successful deploy with green containers: a schema one migration behind, a
# worker that was never started, docs left enabled, a metrics endpoint exposed
# by accident. Container health says the process is running, which is the
# question nobody needs answered.
#
# Read-only and unauthenticated: it creates no account, uploads nothing, and
# asks nothing. A smoke test that wrote data would need credentials in CI and
# would leave residue in a production tenant.
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://127.0.0.1:8000}}"
FAILURES=0

check() {
  local name="$1"; shift
  if "$@"; then
    echo "ok   ${name}"
  else
    echo "FAIL ${name}" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

get_status() { curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$1"; }
get_body() { curl -sS --max-time 10 "$1"; }

liveness_ok() { [[ "$(get_status "${BASE_URL}/health")" == "200" ]]; }

# Readiness is the one that matters: it proves the process reached PostgreSQL,
# Redis, and object storage. Liveness proves only that it started.
readiness_ok() {
  local body
  body="$(get_body "${BASE_URL}/readyz")" || return 1
  echo "${body}" | grep -q '"status":"ready"'
}

# A response header the observability middleware always sets. Its absence means
# requests are reaching something that is not this application — a stale
# container, or a proxy answering from cache.
correlation_ok() {
  curl -sS -o /dev/null -D - --max-time 10 "${BASE_URL}/health" 2>/dev/null \
    | grep -qi '^x-request-id:'
}

# Interactive docs in production hand an attacker a complete, accurate map of
# the API surface. This is the check most likely to catch a real mistake,
# because the setting defaults to on.
docs_closed() {
  [[ "${EXPECT_DOCS:-closed}" == "open" ]] && return 0
  local status
  status="$(get_status "${BASE_URL}/docs")"
  [[ "${status}" == "404" ]]
}

# The scrape endpoint has no authentication of its own. Reachable from outside
# the network boundary, it publishes request volumes and error rates.
metrics_not_public() {
  [[ "${EXPECT_METRICS:-closed}" == "open" ]] && return 0
  local status
  status="$(get_status "${BASE_URL}/metrics")"
  [[ "${status}" == "404" ]]
}

# Security headers survive the reverse proxy. A proxy that strips them leaves
# the browser with none of the protections the application sets.
security_headers_ok() {
  curl -sS -o /dev/null -D - --max-time 10 "${BASE_URL}/health" 2>/dev/null \
    | grep -qi '^x-content-type-options: nosniff'
}

echo "Smoke checks against ${BASE_URL}"
check "liveness" liveness_ok
check "readiness (database, queue, object storage)" readiness_ok
check "correlation header present" correlation_ok
check "interactive docs closed" docs_closed
check "metrics endpoint not publicly reachable" metrics_not_public
check "security headers survive the proxy" security_headers_ok

echo
echo "Not covered here, and worth checking by hand on a first deploy:"
echo "  - the worker is running (upload a document and watch it reach 'ready')"
echo "  - TLS terminates in front of this URL and redirects plain HTTP"

if [[ ${FAILURES} -gt 0 ]]; then
  echo "${FAILURES} check(s) failed" >&2
  exit 1
fi
echo "all checks passed"
