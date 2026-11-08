#!/bin/bash
# FraiseQL Grafana Dashboard Import Script
# Automatically imports all FraiseQL dashboards into Grafana

set -e

# Configuration
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
DASHBOARD_DIR="$(dirname "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "FraiseQL Grafana Dashboard Import"
echo "=========================================="
echo ""
echo "Grafana URL: $GRAFANA_URL"
echo "Dashboard Directory: $DASHBOARD_DIR"
echo ""

# Check if Grafana is accessible
echo "Checking Grafana connectivity..."
if ! curl -s -o /dev/null -w "%{http_code}" -u "$GRAFANA_USER:$GRAFANA_PASSWORD" "$GRAFANA_URL/api/health" | grep -q "200"; then
    echo -e "${RED}ERROR: Cannot connect to Grafana at $GRAFANA_URL${NC}"
    echo "Please ensure:"
    echo "  1. Grafana is running"
    echo "  2. GRAFANA_URL is correct"
    echo "  3. GRAFANA_USER and GRAFANA_PASSWORD are correct"
    exit 1
fi
echo -e "${GREEN}✓ Grafana is accessible${NC}"
echo ""

# Create FraiseQL folder in Grafana
echo "Creating FraiseQL folder in Grafana..."
FOLDER_RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
  -d '{"title":"FraiseQL"}' \
  "$GRAFANA_URL/api/folders" 2>/dev/null || echo '{"id":0}')

FOLDER_ID=$(echo "$FOLDER_RESPONSE" | grep -o '"id":[0-9]*' | head -1 | cut -d':' -f2)

if [ -z "$FOLDER_ID" ] || [ "$FOLDER_ID" = "0" ]; then
    # Folder might already exist, try to get it
    FOLDER_ID=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
        "$GRAFANA_URL/api/folders" | \
        grep -A5 '"title":"FraiseQL"' | \
        grep -o '"id":[0-9]*' | head -1 | cut -d':' -f2)
fi

if [ -z "$FOLDER_ID" ] || [ "$FOLDER_ID" = "0" ]; then
    echo -e "${YELLOW}Warning: Could not create/find FraiseQL folder, importing to General folder${NC}"
    FOLDER_ID=0
else
    echo -e "${GREEN}✓ FraiseQL folder ready (ID: $FOLDER_ID)${NC}"
fi
echo ""

# Function to import a dashboard
import_dashboard() {
    local dashboard_file=$1
    local dashboard_name=$(basename "$dashboard_file" .json)

    echo -n "Importing $dashboard_name... "

    # Read dashboard JSON and wrap it with folder info
    local dashboard_json=$(cat "$dashboard_file")
    local import_payload=$(cat <<EOF
{
  "dashboard": $(echo "$dashboard_json" | jq '.dashboard'),
  "folderId": $FOLDER_ID,
  "overwrite": true
}
EOF
)

    # Import dashboard
    local response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
        -d "$import_payload" \
        "$GRAFANA_URL/api/dashboards/db")

    # Check if import was successful
    if echo "$response" | grep -q '"status":"success"'; then
        local dashboard_url=$(echo "$response" | grep -o '"url":"[^"]*"' | cut -d'"' -f4)
        echo -e "${GREEN}✓${NC}"
        echo "  URL: $GRAFANA_URL$dashboard_url"
    else
        echo -e "${RED}✗${NC}"
        echo "  Error: $response"
        return 1
    fi
}

# Import PostgreSQL datasource if not exists
echo "Checking PostgreSQL datasource..."
DATASOURCE_EXISTS=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
    "$GRAFANA_URL/api/datasources/name/PostgreSQL" 2>/dev/null || echo "not found")

if echo "$DATASOURCE_EXISTS" | grep -q "not found"; then
    echo -e "${YELLOW}PostgreSQL datasource not found.${NC}"
    echo "Please create a PostgreSQL datasource with the following settings:"
    echo "  Name: PostgreSQL"
    echo "  Type: PostgreSQL"
    echo "  Host: your-postgres-host:5432"
    echo "  Database: your-database-name"
    echo "  User: your-postgres-user"
    echo "  SSL Mode: require (for production)"
    echo ""
    echo "Or set the following environment variables and re-run this script:"
    echo "  POSTGRES_HOST"
    echo "  POSTGRES_DB"
    echo "  POSTGRES_USER"
    echo "  POSTGRES_PASSWORD"
    echo ""

    # Optionally create datasource automatically if env vars are set
    if [ -n "$POSTGRES_HOST" ] && [ -n "$POSTGRES_DB" ] && [ -n "$POSTGRES_USER" ] && [ -n "$POSTGRES_PASSWORD" ]; then
        echo "Creating PostgreSQL datasource from environment variables..."
        curl -s -X POST \
            -H "Content-Type: application/json" \
            -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
            -d '{
                "name": "PostgreSQL",
                "type": "grafana-postgresql-datasource",
                "url": "'"$POSTGRES_HOST"'",
                "database": "'"$POSTGRES_DB"'",
                "user": "'"$POSTGRES_USER"'",
                "secureJsonData": {
                    "password": "'"$POSTGRES_PASSWORD"'"
                },
                "jsonData": {
                    "sslmode": "require",
                    "maxOpenConns": 0,
                    "maxIdleConns": 2,
                    "connMaxLifetime": 14400
                }
            }' \
            "$GRAFANA_URL/api/datasources" > /dev/null
        echo -e "${GREEN}✓ PostgreSQL datasource created${NC}"
    fi
else
    echo -e "${GREEN}✓ PostgreSQL datasource exists${NC}"
fi
echo ""

# The performance dashboard reads Prometheus (the /metrics endpoint of setup_metrics)
echo "Checking Prometheus datasource..."
if curl -s -u "$GRAFANA_USER:$GRAFANA_PASSWORD" "$GRAFANA_URL/api/datasources" | grep -q '"type":"prometheus"'; then
    echo -e "${GREEN}✓ Prometheus datasource exists${NC}"
else
    echo -e "${YELLOW}No Prometheus datasource: the Performance Metrics dashboard will show no data.${NC}"
    echo "Add one scraping your app's GET /metrics (fraiseql.monitoring.setup_metrics)."
fi
echo ""

# Import all dashboards
echo "Importing dashboards..."
echo ""

DASHBOARD_FILES=(
    "error_monitoring.json"
    "performance_metrics.json"
    "database_pool.json"
    "apq_effectiveness.json"
)

IMPORT_COUNT=0
FAILED_COUNT=0

for dashboard in "${DASHBOARD_FILES[@]}"; do
    dashboard_path="$DASHBOARD_DIR/$dashboard"
    if [ -f "$dashboard_path" ]; then
        if import_dashboard "$dashboard_path"; then
            IMPORT_COUNT=$((IMPORT_COUNT + 1))
        else
            FAILED_COUNT=$((FAILED_COUNT + 1))
        fi
    else
        echo -e "${YELLOW}Warning: Dashboard file not found: $dashboard${NC}"
    fi
done

echo ""
echo "=========================================="
echo "Import Summary"
echo "=========================================="
echo -e "Successfully imported: ${GREEN}$IMPORT_COUNT${NC}"
echo -e "Failed: ${RED}$FAILED_COUNT${NC}"
echo ""

if [ $IMPORT_COUNT -gt 0 ]; then
    echo -e "${GREEN}✓ Dashboards are now available in Grafana!${NC}"
    echo ""
    echo "Access your dashboards at:"
    echo "  $GRAFANA_URL/dashboards"
    echo ""
    echo "Each dashboard has a 'datasource' variable (top of the dashboard):"
    echo "  pick the PostgreSQL database holding the FraiseQL tables, or your Prometheus."
    echo "Error Monitoring also has an 'environment' variable: the environment"
    echo "  your PostgreSQLErrorTracker was created with (default: production)."
fi

exit $FAILED_COUNT
