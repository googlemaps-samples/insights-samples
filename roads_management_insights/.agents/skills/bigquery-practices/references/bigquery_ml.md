# Capability: BigQuery ML
**Stage**: GA (General Availability)
**Product Source**: BigQuery

## 1. General BigQuery ML Capabilities
Training and deploying machine learning models directly within BigQuery.

- **Model Management**: `CREATE MODEL` syntax to define and train models without moving data.
- **Support Algorithms**: Native support for Linear Regression, Time-series (ARIMA+), and K-Means clustering.
- **In-Database Inference**: Use `ML.PREDICT` or `ML.FORECAST` to generate insights on live data.
- **Evaluation Tools**: `ML.EVALUATE` to assess model precision and reliability.

## 2. RMI Predictive Modeling
Applying ML patterns to historical Road Management Insights.

- **Travel Time Forecasting**: Training time-series models on `duration_in_seconds` to predict expected traffic impact for future dates.
- **Behavioral Route Clustering**: Using K-Means to group routes based on their `duration_ratio` patterns (e.g., identifying "Commuter" vs. "Delivery" routes).
- **Anomaly Scoring**: Using ML to establish a dynamic baseline for "Normal" traffic and flag records with a high reconstruction error as suspicious.
