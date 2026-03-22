#!/usr/bin/env bash

PREFIX=""

curl -X POST "http://localhost:9200/${PREFIX}_case,${PREFIX}_file/_update_by_query?conflicts=proceed" \
  -H 'Content-Type: application/json' \
  -d '{
  "script": {
    "source": "void processNested(def obj) { if (obj instanceof Map) { if (obj.containsKey(\"object_id\")) { obj.file_id = obj.object_id; } for (entry in obj.entrySet()) { processNested(entry.getValue()); } } else if (obj instanceof List) { for (item in obj) { processNested(item); } } } processNested(ctx._source);",
    "lang": "painless"
  },
  "query": {
    "match_all": {}
  }
}'
