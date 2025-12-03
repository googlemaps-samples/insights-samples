# Evaluating Utility Pole Image Classification with an LLM Judge

This notebook demonstrates a pipeline for evaluating and comparing the performance of two different Gemini models (Gemini 2.5 Flash and Gemini 2.5 Pro) on an image classification task. The goal is to classify the material and type of utility poles from images stored in Google Cloud Storage.

## Workflow

1.  **Data Fetching**: The notebook queries a BigQuery table to get a list of GCS URIs for utility pole images.
2.  **Image Classification**: For each image, it uses both the `gemini-2.5-flash` and `gemini-2.5-pro` models to identify:
    *   The pole's material (e.g., "wood", "metal", "concrete").
    *   The pole's type (e.g., "Street light", "High tension power transmission", "electricity pole").
3.  **LLM as a Judge**: A separate function (`judge_outputs`) is implemented where a Gemini model acts as a "judge." It takes the JSON outputs from the two classification models and determines if they are semantically the same.
4.  **Analysis**: The notebook calculates the overall agreement percentage between the two models.
5.  **Review Disagreements**: It displays a sample of the images and corresponding outputs where the models disagreed, allowing for a qualitative analysis of the differences.

## How to Use

1.  **Configuration**: Set the `PROJECT_ID`, `REGION`, `DATASET_ID`, and `TABLE_ID` variables in the notebook to match your Google Cloud environment.
2.  **Execution**: Run the cells sequentially to perform the evaluation.
3.  **Results**: The final cells will output the aggregate agreement score and a table of disagreements for review.
