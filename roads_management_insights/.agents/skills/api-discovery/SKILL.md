---
name: api-discovery
description:
  Expert guidance and tools for the Google API Discovery Service. Use to
  discover available Google APIs, their versions, and fetch their discovery
  documents to understand their structure and methods.
---

# API Discovery

## Overview

The Google API Discovery Service provides a list of Google APIs and their
metadata. This skill enables you to discover available APIs and fetch their
"Discovery Documents" which describe the API's structure, methods, and schemas.

## Quick Start

### 1. List All Available APIs

To see a list of all Google APIs:

```bash
source scripts/discovery_v1.sh
discovery_v1_list
```

### 2. Find a Specific API by Name

To find all versions of the "BigQuery" API:

```bash
source scripts/discovery_v1.sh
discovery_v1_list "bigquery"
```

### 3. Fetch a Discovery Document

To get the discovery document for the "Analytics Hub" API v1:

```bash
source scripts/discovery_v1.sh
discovery_v1_get_rest "analyticshub" "v1"
```

## Key Tasks

### Discovering APIs

- **List All**: `discovery_v1_list` returns a JSON directory of all public
  Google APIs.
- **Filter by Name**: Use the `name` argument in `discovery_v1_list` to narrow
  down results.
- **Preferred Versions**: Use the `preferred=true` argument to only see the
  recommended version for each API.

### Understanding API Structure

- **Fetch Doc**: `discovery_v1_get_rest` retrieves the full REST discovery
  document for an API.
- **Parse Doc**: Use the helper functions in `scripts/discovery_v1_helpers.sh`
  to extract key information like `revision` or `baseUrl`.

## Resources

- **`scripts/discovery_v1.sh`**: Primary service client for listing and fetching
  discovery documents.
- **`scripts/discovery_v1_helpers.sh`**: Utility functions for parsing discovery
  documents.
- **`references/discoveryDocs/`**: Discovery document for the Discovery Service
  itself.
