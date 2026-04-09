# Route Registration Export Tool

This tool provides a way to update an RMI Project Export JSON file with new routes from a CSV data source.

## Overview

The tool reads a base export JSON file (typically exported from the RMI interface), parses a CSV file containing route geometries (in WKT format), and appends these new routes to the JSON file. It automatically handles:
- Coordinate extraction from WKT (LINESTRING or MULTILINESTRING).
- Polyline encoding for the Google Roads API.
- Bounding box and center point calculation.
- UUID generation for new routes.

## Files

- `route_registration_tool.py`: The main Python script that performs the conversion.
- `config.yaml`: Configuration file for project info, file paths, and CSV format.
- `base_export.json`: A template export file used as the starting point.
- `sample_export.json`: A sample output file containing the merged route data.

## Prerequisites

- Python 3.x
- `PyYAML` library

To install dependencies:
```bash
pip install PyYAML
```

## Usage

1. Configure your project details and file paths in `config.yaml`.
2. Ensure `base_export.json` exists (or point to your own export file in `config.yaml`).
3. Run the script:

```bash
python3 route_registration_tool.py config.yaml
```

The script will generate a new JSON file as specified in the `output_export_json_file` path of your configuration.
