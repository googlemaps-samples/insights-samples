# Route Registration Export Tool

This tool manages RMI Project Export JSON files by merging new routes from GeoJSON data.

## Overview

The tool reads a GeoJSON file containing route geometries (LineStrings), parses the features, and either generates a new RMI project export JSON or updates an existing one. It automatically handles:
- Coordinate extraction from GeoJSON.
- Polyline encoding for the Google Roads API.
- Bounding box and center point calculation.
- UUID generation for new routes.
- Merging with existing export files.

## Files

- `main.py`: The main Python script that performs the conversion and merging.
- `config.yaml`: Configuration file for project metadata, file paths, and route settings.
- `sample_input.geojson`: A sample GeoJSON input file with redacted real-world geometries.
- `sample_project.json`: A sample RMI project export file (redacted version of the original Boston export).

## Prerequisites

- Python 3.x
- `PyYAML` library

To install dependencies:
```bash
pip install PyYAML
```

## Usage

1. Configure your project details and file paths in `config.yaml`.
2. (Optional) Provide an existing export JSON in the `base_export_json_file` path to merge new routes into it.
3. Run the script:

```bash
python3 main.py config.yaml
```

The script will generate or update the JSON file as specified in the `output_export_json_file` path of your configuration.
