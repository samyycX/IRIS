// Create unified embedding nodes and vector index support.
CREATE CONSTRAINT embedding_embedding_key IF NOT EXISTS
FOR (embedding:Embedding) REQUIRE embedding.embedding_key IS UNIQUE;

CREATE VECTOR INDEX embedding_index IF NOT EXISTS
FOR (embedding:Embedding) ON (embedding.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
};

// Mark existing pages and entities as pending for the first backfill.
MATCH (page:Page)
SET page.embedding_sync_status = coalesce(page.embedding_sync_status, 'pending'),
    page.embedding_last_error = coalesce(page.embedding_last_error, null),
    page.embedding_target_hash = coalesce(page.embedding_target_hash, null);

MATCH (entity:Entity)
SET entity.embedding_sync_status = coalesce(entity.embedding_sync_status, 'pending'),
    entity.embedding_last_error = coalesce(entity.embedding_last_error, null),
    entity.embedding_target_hash = coalesce(entity.embedding_target_hash, null);
