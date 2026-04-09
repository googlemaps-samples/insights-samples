# Route Registration Export Update Tool

This tool provides a way to update an RMI Project Export JSON file with new routes from a CSV data source.

## Overview

The tool reads a base export JSON file (typically exported from the RMI interface), parses a CSV file containing route geometries (in WKT format), and appends these new routes to the JSON file. It automatically handles:
- Coordinate extraction from WKT.
- Polyline encoding for the Google Roads API.
- Bounding box and center point calculation.
- UUID generation for new routes.

## Files

- `update_export.py`: The main Python script that performs the conversion.
- `config.yaml`: Configuration file for project info, file paths, and CSV format.
- `sample_export_data.json`: A sample output file containing the merged route data.

## Prerequisites

- Python 3.x
- `PyYAML` library

To install dependencies:
```bash
pip install PyYAML
```

## Usage

1. Configure your project details and file paths in `config.yaml`.
2. Run the script:

```bash
python3 update_export.py config.yaml
```

The script will generate a new JSON file as specified in the `output_json` path of your configuration.
