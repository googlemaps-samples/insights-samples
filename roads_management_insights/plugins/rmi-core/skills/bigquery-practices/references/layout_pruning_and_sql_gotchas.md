# Physical Layout, Pruning Verification & SQL Gotchas (field lessons)

Measured on a 3.75M-row, 10.5 GB table of monthly embedding snapshots (36 months × ~104k S2 cells), stored as six physical layouts with identical columns. Billed bytes come from `INFORMATION_SCHEMA.JOBS_BY_USER` with `--nouse_cache`.

## 1. Proving a (linked) table has no partitioning or clustering

Metadata alone is not proof. Combine:
1. `bq show --format=json` → `timePartitioning`, `rangePartitioning`, `clustering`. Analytics Hub linked datasets **do** expose these, as a linked dataset with day partitions showed.
2. `INFORMATION_SCHEMA.PARTITIONS`: a single row with `partition_id = NULL` means unpartitioned.
3. `INFORMATION_SCHEMA.COLUMNS`: `is_partitioning_column`, `clustering_ordinal_position`. Note that `INFORMATION_SCHEMA.TABLES.ddl` is `NULL` for linked tables.
4. **Decisive: a real run.** Filter on the suspected key, then read `total_bytes_billed` and the input-stage `records_read` (`SUM(records_read) FROM UNNEST(job_stages) WHERE name LIKE '%Input%'`). Reading all rows means no pruning.

Pitfalls:
- **Dry runs ignore cluster pruning.** A clustered query dry-ran at 10.0 GB and billed 1.85 GB.
- **`LIMIT` stops early.** The low row count looks like pruning but is not.

## 2. Choosing a layout for snapshot × entity tables

| Access pattern | Month partition + cluster by entity id | No partition, cluster by `(entity id, date)` |
|:--|--:|--:|
| One snapshot, everything | **0.28 GB** | 9.98 GB |
| One entity, all 36 months | 1.93 GB | **0.06 GB** |
| Map viewport, one month | **0.06 GB** | 0.19 GB |
| Map viewport, all months | 2.26 GB | **0.19 GB** |

- **Each partition costs at least about one storage block** (~50 MB here) for point lookups that span every partition. 36 partitions turn a 0.06 GB lookup into ~1.9 GB.
- **Unpartitioned tables do not prune on a second cluster key alone.** `CLUSTER BY id, date` with only a date filter still scans everything.
- If both patterns matter, keep two copies (storage is cheap compared with repeated scans).

## 3. Free geographic pruning from a space-filling-curve key

Clustering by a Hilbert-ordered INT64 key (an S2 cell id) makes every storage block spatially compact. BigQuery then prunes `ST_INTERSECTSBOX(centroid, …)` filters on a **separate** GEOGRAPHY column through per-block statistics: 10.13 → 0.06 GB, with no clustering on the geography itself. Clustering on the GEOGRAPHY column gave no further gain.

- **Keep the INT64 key, not a decimal STRING.** String order is not spatial, and signed negative ids sort apart.
- **For exact range filters,** a covering S2 cell `c` maps to the contiguous range `[c - lsb + 1, c + lsb - 1]` where `lsb = c & -c`.

## 4. Predicates that do not prune

- **Dynamic predicates:** `WHERE id IN (SELECT id FROM dim WHERE ST_INTERSECTSBOX(...))` did **not** prune clusters (0.29 GB on the partition, 10 GB unpartitioned). Resolve the ids or ranges to **literals** first, with a two-step query or client-side parameters.
- **Filters through a join:** filters applied through a join to a dimension table lose cluster pruning. Duplicate the columns you filter on (e.g. centroid, primary region id) into the fact table.

## 5. SQL gotchas

| Symptom | Cause | Fix |
|:--|:--|:--|
| `SAFE with function ml.distance is not supported` | `SAFE.` prefix not supported for `ML.DISTANCE` | Guard inputs instead |
| `Cannot compute cosine distance against zero vector` | An all-zero vector | Append an epsilon dimension: `ML.DISTANCE(ARRAY_CONCAT(x,[1e-9]), ARRAY_CONCAT(y,[1e-9]), 'COSINE')` |
| `User-defined function name 'cos' conflicts with a reserved built-in function name` | Reserved name | Name it `cossim` |
| `Correlated subqueries that reference other tables are not supported…` in `INSERT … SELECT` | Per-row lookups into a temp table | Pre-aggregate with `ARRAY_AGG(STRUCT(...) ORDER BY …)` per key and join |
| A multi-minute catalogue query | `x NOT IN UNNEST(big_array)` across rows (O(n²)) | Anti-join (`LEFT JOIN … WHERE right.key IS NULL`) |
| Inflated counts (e.g. 9 ids per name instead of 1) | `FROM t, UNNEST(ids) id, UNNEST(names) name` is a cross join | Zip parallel arrays: `UNNEST(names) n WITH OFFSET o JOIN UNNEST(ids) i WITH OFFSET o2 ON o = o2`; better, publish `ARRAY<STRUCT<id, name>>` |
| `UPDATE` exceeded `maximum_bytes_billed` | DML bills the whole table | Size the cap to the table |
| `Label value "L0_asis" has invalid characters` | Label values must be lowercase | `tr '[:upper:]' '[:lower:]'` |

## 6. Single-scan change tables with `LAG()`

Compute month-over-month and year-over-year deltas in one pass, instead of self-joins that rescan the vector column:

```sql
WITH lagged AS (
  SELECT *, LAG(snapshot_date, 12) OVER w d12, LAG(vec, 12) OVER w v12
  FROM t WINDOW w AS (PARTITION BY id ORDER BY snapshot_date))
SELECT id, snapshot_date,
  IF(d12 = DATE_SUB(snapshot_date, INTERVAL 12 MONTH), ML.DISTANCE(vec, v12, 'COSINE'), NULL) AS yoy
FROM lagged;
```

The date check drops lags that span gaps in an entity's history. Store only the scalar results (a vector-free table is MBs instead of GBs).

## 7. Measuring spend correctly

When summing `total_bytes_billed` from `INFORMATION_SCHEMA.JOBS_BY_USER`, exclude `statement_type = 'SCRIPT'` parent jobs. Multi-statement scripts otherwise count twice (17.8 GB reported vs 8.9 GB real). Also exclude jobs with `error_result`.

## 8. Reusable Layout Benchmark & S2 Range Script

[`scripts/bench_table_layouts.sh`](../scripts/bench_table_layouts.sh) provides both a CLI benchmark runner and sourceable helpers (`get_layout_clauses`, `build_s2_covering_range_sql`, `build_jobs_benchmark_report_sql`, `build_safe_cosine_distance_expr`).
