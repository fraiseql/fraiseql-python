<!-- Skip to main content -->
---

title: Elasticsearch Search Examples for FraiseQL Events
description: This document shows practical examples of querying FraiseQL events in Elasticsearch.
keywords: []
tags: ["documentation", "reference"]
---

# Elasticsearch Search Examples for FraiseQL Events

This document shows practical examples of querying FraiseQL events in Elasticsearch.

## Basic Search Examples

### Search by Event Type

Find all "created" events:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "event_type": "Created"
      }
    },
    "size": 50
  }'
```
<!-- Code example in TEXT -->

### Search by Entity Type

Find all events affecting "Order" entities:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "entity_type": "Order"
      }
    },
    "sort": [{"timestamp": "desc"}],
    "size": 100
  }'
```
<!-- Code example in TEXT -->

### Search by User

Find all events triggered by a specific user:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "user_id": "user-123"
      }
    },
    "sort": [{"timestamp": "desc"}]
  }'
```
<!-- Code example in TEXT -->

## Advanced Queries

### Full-Text Search

Find events with specific text in any field:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "match": {
        "search_text": "payment failed"
      }
    },
    "highlight": {
      "fields": {
        "search_text": {}
      }
    },
    "size": 50
  }'
```
<!-- Code example in TEXT -->

### Date Range Query

Find events in the last 24 hours:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "range": {
        "timestamp": {
          "gte": "now-24h"
        }
      }
    },
    "sort": [{"timestamp": "desc"}],
    "size": 100
  }'
```
<!-- Code example in TEXT -->

### Combination Query (AND/OR)

Find order creation events from the last 7 days:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"term": {"event_type": "Created"}},
          {"term": {"entity_type": "Order"}},
          {"range": {"timestamp": {"gte": "now-7d"}}}
        ]
      }
    },
    "sort": [{"timestamp": "desc"}]
  }'
```
<!-- Code example in TEXT -->

## Aggregations

### Event Type Distribution

Count events by type (last 7 days):

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {
      "range": {
        "timestamp": {
          "gte": "now-7d"
        }
      }
    },
    "aggs": {
      "by_event_type": {
        "terms": {
          "field": "event_type",
          "size": 50
        }
      }
    }
  }'
```
<!-- Code example in TEXT -->

### Entity Type Distribution

Count events by entity type:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "aggs": {
      "by_entity_type": {
        "terms": {
          "field": "entity_type",
          "size": 50
        }
      }
    }
  }'
```
<!-- Code example in TEXT -->

### Timeline Histogram

Events per hour over the last 48 hours:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {
      "range": {
        "timestamp": {
          "gte": "now-48h"
        }
      }
    },
    "aggs": {
      "events_per_hour": {
        "date_histogram": {
          "field": "timestamp",
          "fixed_interval": "1h"
        }
      }
    }
  }'
```
<!-- Code example in TEXT -->

## Debugging Workflows

### Find Events by Entity ID

Get all events related to a specific entity:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"term": {"entity_type": "Order"}},
          {"term": {"entity_id": "550e8400-e29b-41d4-a716-446655440000"}}
        ]
      }
    },
    "sort": [{"timestamp": "asc"}],
    "size": 1000
  }'
```
<!-- Code example in TEXT -->

### Find Failed Payment Events

Search for events containing payment errors:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"match": {"search_text": "payment"}},
          {"match": {"search_text": "failed"}}
        ],
        "filter": [
          {"range": {"timestamp": {"gte": "now-24h"}}}
        ]
      }
    },
    "highlight": {
      "fields": {
        "search_text": {"number_of_fragments": 3}
      }
    },
    "sort": [{"timestamp": "desc"}],
    "size": 100
  }'
```
<!-- Code example in TEXT -->

## Using with Kibana

### Create a Data View

1. Open Kibana: `http://localhost:5601`
2. Go to **Stack Management** → **Data Views**
3. Click **Create data view**
4. Name: `FraiseQL-events`
5. Index pattern: `FraiseQL-events-*`
6. Timestamp field: `timestamp`
7. Click **Save data view**

### Create a Visualization

#### Events Over Time

1. Go to **Visualize**
2. Click **Create visualization**
3. Select **Line chart**
4. Data source: `FraiseQL-events`
5. Metrics: Count
6. Bucket aggregations: Date histogram on `timestamp` (1 hour interval)
7. Click **Save**

#### Top Event Types

1. Go to **Visualize**
2. Click **Create visualization**
3. Select **Bar vertical**
4. Data source: `FraiseQL-events`
5. Metrics: Count
6. Bucket aggregations: Terms on `event_type`
7. Click **Save**

#### Events by User

1. Go to **Visualize**
2. Click **Create visualization**
3. Select **Table**
4. Data source: `FraiseQL-events`
5. Metrics: Count
6. Bucket aggregations: Terms on `user_id`
7. Sort by count descending
8. Click **Save**

## Performance Tips

### Use Filters for Better Performance

Filters are cached and faster than queries:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "bool": {
        "filter": [
          {"term": {"entity_type": "Order"}},
          {"range": {"timestamp": {"gte": "now-7d"}}}
        ],
        "must": [
          {"match": {"search_text": "payment"}}
        ]
      }
    }
  }'
```
<!-- Code example in TEXT -->

### Limit Fields Retrieved

Only retrieve needed fields for faster response:

```bash
<!-- Code example in BASH -->
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {...},
    "_source": ["event_id", "event_type", "timestamp", "user_id"],
    "size": 100
  }'
```
<!-- Code example in TEXT -->

### Use Search After for Pagination

More efficient than from/size for large result sets:

```bash
<!-- Code example in BASH -->
# Get first page
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {...},
    "sort": [{"timestamp": "desc"}, {"_id": "desc"}],
    "size": 100
  }'

# Get next page (use last sort values from previous response)
curl -X POST "localhost:9200/FraiseQL-events-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {...},
    "sort": [{"timestamp": "desc"}, {"_id": "desc"}],
    "size": 100,
    "search_after": ["2025-01-25T12:34:56.789Z", "event-id-here"]
  }'
```
<!-- Code example in TEXT -->

## Monitoring Queries

### Check Cluster Health

```bash
<!-- Code example in BASH -->
curl "localhost:9200/_cluster/health?pretty"
```
<!-- Code example in TEXT -->

### Monitor Query Performance

```bash
<!-- Code example in BASH -->
# Slow log for queries > 500ms
curl "localhost:9200/_cat/indices/FraiseQL-*?v&sort=store.size:desc"
```
<!-- Code example in TEXT -->

### Check Index Statistics

```bash
<!-- Code example in BASH -->
curl "localhost:9200/FraiseQL-events-*/_stats?pretty"
```
<!-- Code example in TEXT -->
