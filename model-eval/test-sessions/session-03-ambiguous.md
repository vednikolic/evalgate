# Session Summary

## What was done
- Investigated slow database queries in the analytics dashboard. Found that the monthly aggregation query was doing a full table scan on 2M rows.
- Added a composite index on (user_id, created_at) which brought the query from 4.2s to 180ms.
- Reviewed the query planner output to confirm the index is being used.
- Discussed whether to add caching on top of the index optimization. Decided the index alone is sufficient for now since the query runs at most once per page load.
- Updated the migration script to include the new index with a concurrent creation strategy to avoid locking the table in production.

## Decisions made
- [settled] Add composite index rather than separate single-column indexes. The query filters on user_id first, then sorts by created_at, so the composite index covers both operations in one B-tree traversal.
- [settled] Use CREATE INDEX CONCURRENTLY to avoid table locks during migration. Longer to build but does not block reads or writes.
- [tentative] Skip caching layer for now. Revisit if dashboard latency requirements tighten below 200ms.

## Learnings
- Composite index column order matters. The high-cardinality column (user_id) should come first when the query uses equality on one column and range/sort on the other.
- EXPLAIN ANALYZE is more reliable than EXPLAIN alone because it shows actual vs estimated row counts. Estimated counts can be wildly off on tables without recent ANALYZE runs.
- Concurrent index creation in PostgreSQL requires the migration to not run inside a transaction block.

## Friction observed
- Had to manually check whether the ORM migration tool supports CONCURRENTLY. It does not by default. Wrote a raw SQL migration instead.

## Connections detected
- Other services with similar aggregation queries might benefit from the same indexing strategy.

## Unfinished work
- Monitor query performance in production after the index is deployed
- Consider adding pg_stat_statements to track slow queries proactively
