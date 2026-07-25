#!/usr/bin/env bash
# Requirement-scored verification for PR 19 (authentication and workspace UI).
#
# One command, 29 binary checks, machine-scored. Prints PASS/FAIL per check,
# appends the score triple to .verify-pr19.log, exits non-zero unless every
# check passes. Group A are the repository quality gates, group B maps each
# acceptance-criteria behaviour to a named test title, group C encodes the
# non-testable constraints (no client token storage, edit scope, commit
# grammar, documented configuration) as greppable assertions.
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
WEB="$ROOT/apps/web"
API="$ROOT/apps/api"
BASE="${VERIFY_BASE_REF:-origin/main}"
ARTIFACTS="$ROOT/.verify-pr19"
mkdir -p "$ARTIFACTS"

a_pass=0
b_pass=0
c_pass=0
first_fail=""

record() { # record <group> <id> <ok>
  local group="$1" id="$2" ok="$3"
  if [ "$ok" -eq 0 ]; then
    printf 'PASS %s\n' "$id"
    case "$group" in
    A) a_pass=$((a_pass + 1)) ;;
    B) b_pass=$((b_pass + 1)) ;;
    C) c_pass=$((c_pass + 1)) ;;
    esac
  else
    printf 'FAIL %s\n' "$id"
    [ -z "$first_fail" ] && first_fail="$id"
  fi
}

# ---------------------------------------------------------------- group A
run_gate() { # run_gate <id> <logfile> <command...>
  local id="$1" log="$2"
  shift 2
  if "$@" >"$ARTIFACTS/$log" 2>&1; then record A "$id" 0; else record A "$id" 1; fi
}

run_gate A1 format.log npm --prefix "$WEB" run format:check
run_gate A2 lint.log npm --prefix "$WEB" run lint
run_gate A3 typecheck.log npm --prefix "$WEB" run typecheck

# A4 also refuses to accept lowered coverage thresholds.
thresholds_ok=1
if [ "$(grep -cE '^ +(branches|functions|lines|statements): (9[0-9]|100),' "$WEB/vitest.config.ts")" -eq 4 ]; then
  thresholds_ok=0
fi
# `--reporter=verbose` prints every test title, which the group B checks match
# against, so a renamed or deleted behaviour test is reported as a failure.
if npm --prefix "$WEB" run test:coverage -- --reporter=verbose \
  >"$ARTIFACTS/test.log" 2>&1 && [ "$thresholds_ok" -eq 0 ]; then
  record A A4 0
else
  record A A4 1
fi

run_gate A5 build.log npm --prefix "$WEB" run build

# A6: backend suite green and server-side authorization untouched by this PR.
# The integration tier needs PostgreSQL, Redis, and MinIO; set VERIFY_API_TESTS
# to run it where Docker is available (CI always does). Everywhere else the
# unit tier still proves the auth/permission logic this PR relies on.
api_auth_diff="$(git diff --name-only "$BASE" -- \
  apps/api/app/auth apps/api/app/routes/auth.py apps/api/app/routes/workspaces.py)"
api_args="${VERIFY_API_TESTS:---ignore=tests/integration --no-cov}"
if [ -x "$API/.venv/bin/pytest" ]; then
  # shellcheck disable=SC2086 -- deliberate word splitting of the arg string
  (cd "$API" && .venv/bin/pytest tests -q $api_args) >"$ARTIFACTS/pytest.log" 2>&1
  api_ok=$?
else
  api_ok=1
  echo "apps/api/.venv/bin/pytest missing" >"$ARTIFACTS/pytest.log"
fi
if [ "$api_ok" -eq 0 ] && [ -z "$api_auth_diff" ]; then record A A6 0; else record A A6 1; fi

# ---------------------------------------------------------------- group B
# Test titles are asserted against the vitest reporter output, so renaming or
# deleting a behaviour test fails the score instead of passing silently.
TEST_OUTPUT="$ARTIFACTS/test.log"
titles_present() { # titles_present <title>...
  local title
  for title in "$@"; do
    grep -Fq "$title" "$TEST_OUTPUT" || return 1
  done
  return 0
}
check_b() { # check_b <id> <title>...
  local id="$1"
  shift
  if titles_present "$@"; then record B "$id" 0; else record B "$id" 1; fi
}

check_b B1 'registers a new account' 'surfaces email_already_registered'
check_b B2 'establishes a session on login' 'surfaces invalid_credentials'
check_b B3 'revokes the refresh token and clears the session cookie'
check_b B4 'redirects unauthenticated visitors to login with a next parameter'
check_b B5 'refreshes an expired access token once and retries' \
  'clears the session when refresh fails'
check_b B6 'renders the loading state' 'renders the empty state' \
  'renders the error state' 'lists the workspaces'
check_b B7 'switches the active workspace'
check_b B8 'shows member management to owners and admins' \
  'hides member management from members and viewers'
check_b B9 'adds a member' 'surfaces user_not_found' \
  'surfaces member_already_exists' 'surfaces cannot_manage_role'
check_b B10 'changes a member role' 'surfaces last_owner'
check_b B11 'removes a member after confirmation'
check_b B12 'renders access denied for insufficient_role' \
  'renders not found for workspace_not_found'
check_b B13 'rejects a malformed API payload'
check_b B14 'labels every field and announces errors'
check_b B15 'renders Tamil copy with a ta language tag'

# ---------------------------------------------------------------- group C
web_sources() {
  # Tracked and staged-but-new sources both count, so a check cannot be dodged
  # by leaving a file untracked.
  {
    git ls-files 'apps/web/**/*.ts' 'apps/web/**/*.tsx' 'apps/web/*.ts'
    git ls-files --others --exclude-standard 'apps/web/**/*.ts' 'apps/web/**/*.tsx' \
      'apps/web/*.ts'
  } | sort -u
}

# C1: browser storage never holds session material.
if web_sources | xargs grep -lE 'localStorage|sessionStorage' 2>/dev/null | grep -q .; then
  record C C1 1
else
  record C C1 0
fi

# C2: raw tokens never appear in client-rendered components.
if git ls-files 'apps/web/components/**' | xargs grep -lE 'access_token|refresh_token' 2>/dev/null |
  grep -q .; then
  record C C2 1
else
  record C C2 0
fi

# C3: edit scope stays inside this feature's surface.
out_of_scope="$(git diff --name-only "$BASE" |
  grep -vE '^(apps/web/|docs/|scripts/|\.env\.example$|\.gitignore$|docker-compose\.yml$|Makefile$)' || true)"
if [ -z "$out_of_scope" ]; then record C C3 0; else record C C3 1; fi

# C4: no secrets or credentials introduced. The patterns are assembled at
# runtime so this script's own source is not what the check matches on.
secret_pattern="$(printf 'PRIVATE %s|%s=[^"$]|%s=[A-Za-z0-9]' KEY SECRET password)"
if git diff "$BASE" -- . ':(exclude)scripts' | grep -E '^\+' |
  grep -qE "$secret_pattern"; then
  record C C4 1
else
  record C C4 0
fi

# C5: Conventional Commit subjects only.
bad_subjects="$(git log --format=%s "$BASE"..HEAD |
  grep -vE '^(feat|fix|docs|test|chore|refactor|perf|build|ci|style)(\([a-z0-9.-]+\))?!?: .+' || true)"
if [ -n "$(git log --format=%s "$BASE"..HEAD)" ] && [ -z "$bad_subjects" ]; then
  record C C5 0
else
  record C C5 1
fi

# C6: docs describe the session model and every new env var the web app reads.
docs_ok=0
grep -qi 'session' "$ROOT/docs/ARCHITECTURE.md" || docs_ok=1
grep -qi 'session' "$ROOT/docs/SECURITY.md" || docs_ok=1
# NODE_ENV is a framework built-in, not deployment configuration.
for env_name in $(web_sources | xargs grep -hoE 'process\.env\.[A-Z0-9_]+' 2>/dev/null |
  sed 's/process\.env\.//' | grep -v '^NODE_ENV$' | sort -u); do
  grep -q "$env_name" "$ROOT/docs/CONFIGURATION.md" || docs_ok=1
done
record C C6 "$docs_ok"

# C7: a pull request targets main and closes the issue.
pr_ok=1
if command -v gh >/dev/null 2>&1; then
  pr_json="$(gh pr view --json baseRefName,body 2>/dev/null || true)"
  if printf '%s' "$pr_json" | grep -q '"baseRefName":"main"' &&
    printf '%s' "$pr_json" | grep -q 'Closes #19'; then
    pr_ok=0
  fi
fi
record C C7 "$pr_ok"

# C8: the roster stays usable on a narrow viewport.
if titles_present 'keeps the member roster usable at 375px'; then
  record C C8 0
else
  record C C8 1
fi

# ---------------------------------------------------------------- score
score="A=$a_pass/6 B=$b_pass/15 C=$c_pass/8"
printf 'SCORE %s\n' "$score"
printf '%s %s first_fail=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$score" \
  "${first_fail:-none}" >>"$ROOT/.verify-pr19.log"
[ -z "$first_fail" ]
