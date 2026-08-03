# Sample Queries for Street View Insights

## Pre-requisites

1. Please ensure you have subscribed to your dataset using instructions [here](https://developers.google.com/maps/documentation/street-view-insights/environment-setup).

2. Install the `bq` [command-line tool](https://docs.cloud.google.com/bigquery/docs/reference/bq-cli-reference#bq_query).

## Running Queries

You will need to substituate your GCP project ID and linked dataset ID.

Set your project ID and dataset ID:

```sh
PROJECT_ID=...
DATASET_ID=...
```

### Observations associated with an asset

Run the `Get_all_observations_for_an_asset_id.sql` query as follows:

```sh
# replace with your actual asset ID of interest
ASSET_ID='t1:...'

bq query \
   --use_legacy_sql=false \
   --project_id=<PROJECT_ID> \
   --dataset_id=<DATASET_ID> \
   --parameter="asset_id_to_query:STRING:${ASSET_ID}" \
   < street_view_insights/cropped/queries/Get_all_observations_for_an_asset_id.sql
```

### Assets with multiple observations

Run the `Get_all_assets_with_multiple_observations.sql` query as follows:

```sh
# replace with your actual asset ID of interest
ASSET_CLASS='ASSET_CLASS_UTILITY_POLE'

bq query \
   --use_legacy_sql=false \
   --project_id=<PROJECT_ID> \
   --dataset_id=<DATASET_ID> \
   --parameter="asset_to_analyze:STRING:${ASSET_CLASS}" \
   < street_view_insights/cropped/queries/Get_all_assets_with_multiple_observations.sql
```

See the [schema reference](https://developers.google.com/maps/documentation/street-view-insights/reference) for other asset classes.

## References

* BigQuery
  * [bq query](https://docs.cloud.google.com/bigquery/docs/reference/bq-cli-reference#bq_query)
  * [Global flags](https://docs.cloud.google.com/bigquery/docs/reference/bq-cli-reference#global_flags)
* Street View Insights
  * [Schema reference](https://developers.google.com/maps/documentation/street-view-insights/reference)
