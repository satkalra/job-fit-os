#!/usr/bin/env bash
# Smoke-tests the app in production-like mode using Docker + local Postgres.
# Requires: docker, docker-compose, .env with real API keys.
set -euo pipefail

BASE_URL="http://localhost:8765"
SIGNUP_TOKEN="test-invite-secret-local"
TEST_EMAIL="smoke+$(date +%s)@test.com"
IMAGE="jobfitos-prod-test"
CONTAINER="jobfitos-smoke"

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; FAILED=$((FAILED+1)); }
info() { echo -e "${YELLOW}▶${NC} $1"; }
FAILED=0

# ── cleanup on exit ────────────────────────────────────────────────────────
cleanup() {
  info "Cleaning up..."
  docker rm -f "$CONTAINER" 2>/dev/null || true
}
trap cleanup EXIT

# ── 1. Build Docker image ────────────────────────────────────────────────────
info "Building Docker image..."
docker build -t "$IMAGE" . 2>&1 | tail -5
pass "Docker image built"

# ── 2. Postgres ─────────────────────────────────────────────────────────────
info "Starting Postgres via docker-compose..."
docker-compose up -d db
info "Waiting for Postgres to be ready..."
for i in $(seq 1 20); do
  docker-compose exec -T db pg_isready -U jobfit -d jobfit_os -q && break
  sleep 1
done
pass "Postgres ready"

# ── 3. Migrations (run inside Docker image) ──────────────────────────────────
info "Running alembic migrations via Docker..."
docker run --rm \
  --network host \
  -e DATABASE_URL="postgresql+asyncpg://jobfit:jobfit@localhost/jobfit_os" \
  -e ENVIRONMENT=production \
  -e SIGNUP_TOKEN="$SIGNUP_TOKEN" \
  -e JWT_SECRET="local-prod-test-secret-32chars!!" \
  "$IMAGE" \
  alembic upgrade head
pass "Migrations applied"

# ── 4. Start app container ───────────────────────────────────────────────────
info "Starting app container on port 8765..."
docker run -d \
  --name "$CONTAINER" \
  --network host \
  -e DATABASE_URL="postgresql+asyncpg://jobfit:jobfit@localhost/jobfit_os" \
  -e ENVIRONMENT=production \
  -e SIGNUP_TOKEN="$SIGNUP_TOKEN" \
  -e JWT_SECRET="local-prod-test-secret-32chars!!" \
  -e BASE_URL="$BASE_URL" \
  -e LOG_LEVEL=WARNING \
  -p 8765:8000 \
  "$IMAGE" > /dev/null

info "Waiting for server to be ready..."
for i in $(seq 1 30); do
  curl -sf "$BASE_URL/health" > /dev/null 2>&1 && break
  sleep 1
done
pass "Server up (Docker)"

# ── helpers ─────────────────────────────────────────────────────────────────
check_status() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" -eq "$expected" ]; then
    pass "$label → HTTP $actual"
  else
    fail "$label → expected $expected got $actual"
    echo "    container logs:"
    docker logs "$CONTAINER" 2>&1 | tail -5 | sed 's/^/    /'
  fi
}

get_status() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# ── 5. Health ────────────────────────────────────────────────────────────────
info "--- Health ---"
STATUS=$(get_status "$BASE_URL/health")
check_status "GET /health" 200 "$STATUS"

SCHEDULER=$(curl -s "$BASE_URL/health" | python3 -c "import sys,json; print(json.load(sys.stdin)['scheduler'])")
if [ "$SCHEDULER" = "running" ]; then
  pass "Scheduler is running"
else
  fail "Scheduler not running (got: $SCHEDULER)"
fi

# ── 6. Signup token enforcement ───────────────────────────────────────────────
info "--- Signup token enforcement ---"
STATUS=$(get_status -X POST "$BASE_URL/users" \
  -H "Content-Type: application/json" \
  -d '{"email":"blocked@test.com","name":"Blocked","profile_type":"engineering","domains":["AI"],"seniority":"senior","briefing_time":"08:00","timezone":"UTC"}')
check_status "POST /users (no token → 403)" 403 "$STATUS"

STATUS=$(get_status -X POST "$BASE_URL/users" \
  -H "Content-Type: application/json" \
  -H "X-Signup-Token: wrong-token" \
  -d '{"email":"blocked@test.com","name":"Blocked","profile_type":"engineering","domains":["AI"],"seniority":"senior","briefing_time":"08:00","timezone":"UTC"}')
check_status "POST /users (wrong token → 403)" 403 "$STATUS"

# ── 7. Create user ───────────────────────────────────────────────────────────
info "--- User lifecycle ---"
SIGNUP_RESP=$(curl -s -X POST "$BASE_URL/users" \
  -H "Content-Type: application/json" \
  -H "X-Signup-Token: $SIGNUP_TOKEN" \
  -d "{\"email\":\"$TEST_EMAIL\",\"name\":\"Smoke Test\",\"profile_type\":\"engineering\",\"domains\":[\"AI Engineering\",\"Backend\"],\"seniority\":\"senior\",\"briefing_time\":\"08:00\",\"timezone\":\"America/New_York\",\"min_salary\":150000}")

USER_ID=$(echo "$SIGNUP_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])" 2>/dev/null || echo "")
MGMT_TOKEN=$(echo "$SIGNUP_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['management_token'])" 2>/dev/null || echo "")

if [ -n "$USER_ID" ] && [ -n "$MGMT_TOKEN" ]; then
  pass "POST /users → user_id=$USER_ID"
else
  fail "POST /users → no user_id or token in response: $SIGNUP_RESP"
fi

# ── 8. Duplicate email ────────────────────────────────────────────────────────
STATUS=$(get_status -X POST "$BASE_URL/users" \
  -H "Content-Type: application/json" \
  -H "X-Signup-Token: $SIGNUP_TOKEN" \
  -d "{\"email\":\"$TEST_EMAIL\",\"name\":\"Dupe\",\"profile_type\":\"engineering\",\"domains\":[\"AI\"],\"seniority\":\"senior\",\"briefing_time\":\"08:00\",\"timezone\":\"UTC\"}")
check_status "POST /users (duplicate email → 400)" 400 "$STATUS"

# ── 9. Get user ───────────────────────────────────────────────────────────────
STATUS=$(get_status "$BASE_URL/users/$USER_ID" -H "Authorization: Bearer $MGMT_TOKEN")
check_status "GET /users/$USER_ID (auth'd)" 200 "$STATUS"

STATUS=$(get_status "$BASE_URL/users/$USER_ID")
check_status "GET /users/$USER_ID (no auth → 422)" 422 "$STATUS"

# ── 10. Patch user ─────────────────────────────────────────────────────────────
STATUS=$(get_status -X PATCH "$BASE_URL/users/$USER_ID" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MGMT_TOKEN" \
  -d '{"preferred_locations":["NYC","Remote"]}')
check_status "PATCH /users/$USER_ID" 200 "$STATUS"

# ── 11. Update weights ────────────────────────────────────────────────────────
STATUS=$(get_status -X PATCH "$BASE_URL/users/$USER_ID/weights" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MGMT_TOKEN" \
  -d '{"weight_role_match":0.35,"weight_skills_match":0.30,"weight_experience_level":0.15,"weight_compensation":0.10,"weight_cultural":0.10}')
check_status "PATCH /users/$USER_ID/weights" 200 "$STATUS"

STATUS=$(get_status -X PATCH "$BASE_URL/users/$USER_ID/weights" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MGMT_TOKEN" \
  -d '{"weight_role_match":0.50,"weight_skills_match":0.50,"weight_experience_level":0.10,"weight_compensation":0.10,"weight_cultural":0.10}')
check_status "PATCH /weights (bad sum → 422)" 422 "$STATUS"

# ── 12. Resume text ───────────────────────────────────────────────────────────
RESUME=$(python3 -c "print('Python engineer FastAPI PostgreSQL Redis Docker AWS ' * 30)")
STATUS=$(get_status -X POST "$BASE_URL/users/$USER_ID/resume/text" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MGMT_TOKEN" \
  -d "{\"resume_text\": \"$RESUME\"}")
check_status "POST /users/$USER_ID/resume/text" 200 "$STATUS"

STATUS=$(get_status -X POST "$BASE_URL/users/$USER_ID/resume/text" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MGMT_TOKEN" \
  -d '{"resume_text": "too short"}')
check_status "POST /resume/text (too short → 422)" 422 "$STATUS"

# ── 13. Dev router not mounted ────────────────────────────────────────────────
info "--- Production safety ---"
STATUS=$(get_status "$BASE_URL/jobs/00000000-0000-0000-0000-000000000000")
check_status "GET /jobs/:id (dev route not mounted → 404)" 404 "$STATUS"

# ── 14. Summary ───────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ]; then
  echo -e "${GREEN}All checks passed. Safe to deploy.${NC}"
else
  echo -e "${RED}$FAILED check(s) failed. Fix before deploying.${NC}"
  docker logs "$CONTAINER" 2>&1 | tail -20
  exit 1
fi
