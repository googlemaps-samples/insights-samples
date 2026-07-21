# Measure Height of Assets with Gemini 2.5 Flash

This notebook demonstrates how to measure the height of assets, such as utility poles, using the Gemini 2.5 Flash model.

## Notebook Description

The primary goal of this notebook is to leverage the advanced multimodal capabilities of Gemini 2.5 Flash to analyze images of assets and estimate their height. It employs a sophisticated prompting strategy to guide the model in its analysis, which involves:

1.  **Image Input:** You'll provide images of assets as input.
2.  **Detailed Prompting:** The notebook uses a detailed prompt that instructs the model to follow a specific analysis flow, leveraging geometrical principles, image understanding, and known reference values.
3.  **Gemini 2.5 Flash Integration:** The Gemini 2.5 Flash model will process the input images and the detailed prompt to estimate the height of the asset.
4.  **Output:** The notebook will output the estimated height, a confidence score, and a detailed reasoning for the estimation.

## What the Notebook Does

The notebook performs the following steps:

1.  **Fetches Image URIs from BigQuery:** It queries a BigQuery table to get the GCS URIs of the images to be analyzed.
2.  **Groups Images by Asset:** It groups the image GCS URIs by their corresponding `asset_id`.
3.  **Estimates Asset Height:** It uses the `estimate_asset_height` function to estimate the height of each asset. This function sends the images and a detailed prompt to the Gemini 2.5 Flash model, which then returns an estimated height, a confidence score, and a detailed reasoning for the estimation.
4.  **Generates a DataFrame:** It compiles the results (asset ID, number of observations, measured height, and confidence score) into a pandas DataFrame.

## Prerequisites for First-Time Users

To successfully run this notebook, please ensure the following:

1.  **Google Cloud Project:** You need an active Google Cloud project.
2.  **Enable APIs:**
    *   **Vertex AI API:** This is essential for accessing and using Gemini models. You can enable it through the Google Cloud Console under "APIs & Services" > "Library".
3.  **Authentication:**
    *   **Google Cloud Authentication:** Ensure your Colab environment is authenticated to your Google Cloud project.
4.  **Input Data:**
    *   **Asset Images:** Prepare the images of the assets you want to measure. These should be uploaded to your Colab environment or accessible from Google Cloud Storage.
5.  **Required Libraries:** The notebook will likely import several libraries. Ensure they are installed.

By following these steps, you should be well-equipped to run this notebook and explore the capabilities of Gemini 2.5 Flash for asset height estimation.