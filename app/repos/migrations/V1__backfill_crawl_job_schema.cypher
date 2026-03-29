// Normalize legacy CrawlJob nodes so the new persisted job store can read them.
MATCH (job:CrawlJob)
SET job.input_type = CASE
        WHEN job.input_type IN ['url', 'instruction', 'entity'] THEN job.input_type
        WHEN coalesce(job.seed, '') STARTS WITH 'http://' OR coalesce(job.seed, '') STARTS WITH 'https://' THEN 'url'
        ELSE 'entity'
    END,
    job.status = CASE
        WHEN job.status IN ['queued', 'running', 'paused', 'completed', 'failed', 'cancelled', 'interrupted'] THEN job.status
        WHEN job.completed_at IS NOT NULL THEN 'completed'
        WHEN coalesce(job.last_error, '') <> '' THEN 'failed'
        WHEN coalesce(job.checkpoint_json, '') <> '' THEN 'interrupted'
        WHEN job.graph_update_json IS NOT NULL THEN 'completed'
        ELSE 'interrupted'
    END,
    job.created_at = coalesce(job.created_at, job.started_at, datetime()),
    job.updated_at = coalesce(job.updated_at, job.completed_at, job.started_at, datetime()),
    job.max_depth = coalesce(toInteger(job.max_depth), 0),
    job.max_pages = coalesce(toInteger(job.max_pages), 0),
    job.visited_count = coalesce(toInteger(job.visited_count), 0),
    job.queued_count = coalesce(toInteger(job.queued_count), 0),
    job.failed_count = coalesce(toInteger(job.failed_count), 0),
    job.events_json = CASE
        WHEN job.events_json IS NULL OR trim(toString(job.events_json)) = '' THEN '[]'
        ELSE toString(job.events_json)
    END,
    job.visited_urls_json = CASE
        WHEN job.visited_urls_json IS NULL OR trim(toString(job.visited_urls_json)) = '' THEN '[]'
        ELSE toString(job.visited_urls_json)
    END,
    job.checkpoint_json = CASE
        WHEN job.checkpoint_json IS NULL OR trim(toString(job.checkpoint_json)) = '' THEN null
        ELSE toString(job.checkpoint_json)
    END,
    job.resume_available = CASE
        WHEN job.resume_available IS NULL THEN coalesce(job.checkpoint_json, '') <> ''
        ELSE job.resume_available
    END,
    job.schema_version = 1;
