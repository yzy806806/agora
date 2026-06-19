#!/bin/bash
# register-team.sh - Register Agora development team agents.
# Phase 15 Part D.4: Dogfooding infrastructure.
#
# Usage:
#   AGORA_URL=http://localhost:8765 ./scripts/register-team.sh
#   AGORA_ADMIN_TOKEN=xxx ./scripts/register-team.sh  # auto-approve
#
# Each agent is registered via POST /api/v1/agents/register.
# If AGORA_REQUIRE_APPROVAL=true (default), an admin must approve
# each agent before it can connect via WebSocket.
set -euo pipefail

AGORA_URL="${AGORA_URL:-http://localhost:8765}"
ADMIN_TOKEN="${AGORA_ADMIN_TOKEN:-}"

# Team agents: id:name:agent_type:capabilities
AGENTS=(
  "coordinator:Coordinator:hermes:orchestration,scheduling"
  "planner:Planner:hermes:research,design"
  "dev-merger:Dev Merger:hermes:development,testing"
  "reviewer:Reviewer:hermes:code-review,quality"
  "releaser:Releaser:hermes:release,deployment"
)

registered=0
skipped=0
failed=0

for agent in "${AGENTS[@]}"; do
  IFS=':' read -r id name atype caps <<< "$agent"
  echo -n "Registering $name ($id)... "
  response=$(curl -s -w "\n%{http_code}" -X POST \
    "${AGORA_URL}/api/v1/agents/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_id\":\"$id\",\"name\":\"$name\",\"agent_type\":\"$atype\",\"capabilities\":[\"${caps//,/\",\"}\"]}" 2>&1) || true
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | head -n -1)

  case "$http_code" in
    201)
      echo "OK (created)"
      registered=$((registered + 1))
      ;;
    409)
      echo "SKIP (already exists)"
      skipped=$((skipped + 1))
      ;;
    *)
      echo "FAIL (HTTP $http_code)"
      echo "  $body"
      failed=$((failed + 1))
      ;;
  esac
done

echo ""
echo "Summary: $registered registered, $skipped skipped, $failed failed"

# If admin token provided, auto-approve all pending agents
if [ -n "$ADMIN_TOKEN" ]; then
  echo ""
  echo "Auto-approving pending agents..."
  for agent in "${AGENTS[@]}"; do
    IFS=':' read -r id name _ <<< "$agent"
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
      "${AGORA_URL}/api/v1/admin/agents/${id}/approve" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}")
    if [ "$http_code" = "200" ]; then
      echo "  Approved: $id"
    else
      echo "  Failed: $id (HTTP $http_code)"
    fi
  done
fi
