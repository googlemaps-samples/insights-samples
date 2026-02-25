# Insights samples

This repository contains samples for the Insights products from Google Maps Platform.

You can learn more about the products on the [product page](https://mapsplatform.google.com/maps-products/geospatial-analytics).

### Street View Insights

[Docs](https://developers.google.com/maps/documentation/imagery-insights)

### Places Insights

[Docs](https://developers.google.com/maps/documentation/placesinsights) | [Demo](https://mapsplatform.google.com/demos/places-insights/)

### Roads Management Insights

[Docs](https://developers.google.com/maps/documentation/roads-management-insights) | [Demo](https://google-rmi-demo-1024202510105.us-central1.run.app/)

## Available Recipe Collections

*   [`places_insights/`](places_insights/): Samples for analyzing the Places Insights BigQuery dataset.
    *   [`notebooks/`](places_insights/notebooks/): Example Google Colab notebooks for querying the dataset and visualizing the results.
        *   [`custom_location_scores/`](places_insights/notebooks/custom_location_scores/): Combines Places Insights data with BigQuery `AI.GENERATE` (Gemini) to calculate and visualize AI-powered suitability scores for real estate listings based on a specific user persona.
        *   [`nevada_site_selection/`](places_insights/notebooks/nevada_site_selection/): Demonstrates a multi-stage site selection workflow for a new coffee shop in Las Vegas, combining competitor analysis, commercial suitability scoring, and target market density on an interactive map.
        *   [`sample_data_demo/`](places_insights/notebooks/sample_data_demo/): A technical introduction demonstrating how to query, aggregate, and visualize Places Insights data in BigQuery using Standard SQL, Python, and the H3 grid system to analyze commercial density across global cities.
        *   [`spot_check_results/`](places_insights/notebooks/spot_check_results/): Illustrates a workflow for spot-checking analytical data by combining H3 density aggregations with the Place Details API to visualize both statistical hotspots and individual locations on an interactive map.
    *   [`places-insights-demo/`](places_insights/places-insights-demo/): Source code for an interactive JavaScript web application demo.
    *   [`sample_queries/`](places_insights/sample_queries/): Sample SQL queries for aggregating location data directly in BigQuery.
*   [`roads_management_insights/`](roads_management_insights/): Recipes for insights related to roads management.
    *   [`route_registration_from_csv/`](roads_management_insights/route_registration_from_csv/): A Python script to create routes in Google Roads API from a CSV file.
*   [`street_view_insights/`](street_view_insights/): Recipes for insights from imagery data.

## License

This project is licensed under the Apache License 2.0 - see the [`LICENSE`](LICENSE) file for details.

## Code of Conduct

This project has adopted the [Google Open Source Community Guidelines](CODE_OF_CONDUCT.md).

## Security

See [`SECURITY.md`](SECURITY.md) for details on how to report security vulnerabilities.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details on how to contribute to this project.