// Initialize the graph schema for the current Source-based domain model.
CREATE CONSTRAINT source_canonical_url IF NOT EXISTS
FOR (source:Source) REQUIRE source.canonical_url IS UNIQUE;

CREATE CONSTRAINT entity_entity_id IF NOT EXISTS
FOR (entity:Entity) REQUIRE entity.entity_id IS UNIQUE;

CREATE CONSTRAINT crawl_job_id IF NOT EXISTS
FOR (job:CrawlJob) REQUIRE job.job_id IS UNIQUE;

CREATE CONSTRAINT embedding_embedding_key IF NOT EXISTS
FOR (embedding:Embedding) REQUIRE embedding.embedding_key IS UNIQUE;

CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS
FOR (entity:Entity) ON (entity.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX source_embedding_index IF NOT EXISTS
FOR (source:Source) ON (source.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX relation_embedding_index IF NOT EXISTS
FOR (embedding:RelationEmbedding) ON (embedding.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE FULLTEXT INDEX entity_fulltext_index IF NOT EXISTS
FOR (entity:Entity) ON EACH [entity.fulltext_text];

CREATE FULLTEXT INDEX source_fulltext_index IF NOT EXISTS
FOR (source:Source) ON EACH [source.fulltext_text];

CREATE FULLTEXT INDEX relation_fulltext_index IF NOT EXISTS
FOR (embedding:RelationEmbedding) ON EACH [embedding.fulltext_text];
