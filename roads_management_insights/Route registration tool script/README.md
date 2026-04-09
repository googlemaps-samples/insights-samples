# Route Registration Export Tool

This tool converts a GeoJSON file (extracted from the Route Registration Tool) into an RMI Project Export JSON format.

## Overview

The tool reads a GeoJSON file containing route geometries (LineStrings), parses the features, and generates a complete RMI project export JSON file. It automatically handles:
- Coordinate extraction from GeoJSON.
- Polyline encoding for the Google Roads API.
- Bounding box and center point calculation.
- UUID generation for new routes.
- Project metadata generation from configuration.

## Files

- `main.py`: The main Python script that performs the conversion.
- `config.yaml`: Configuration file for project metadata, file paths, and route settings.
- `sample_input.geojson`: A sample GeoJSON input file.

## Prerequisites

- Python 3.x
- `PyYAML` library

To install dependencies:
```bash
pip install PyYAML
```

## Usage

1. Configure your project details (name, cloud ID, etc.) and file paths in `config.yaml`.
2. Run the script:

```bash
python3 main.py config.yaml
```

The script will generate a new JSON file as specified in the `output_export_json_file` path of your configuration. This file can then be imported directly into the RMI interface.
