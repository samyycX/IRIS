// Remove node-level embedding sync status in favor of hash comparison.
MATCH (page:Page)
REMOVE page.embedding_sync_status;

MATCH (entity:Entity)
REMOVE entity.embedding_sync_status;

// Ensure relation embedding nodes are distinguishable and can reuse the shared embedding index.
MATCH (embedding:Embedding {source_type: 'relation'})
SET embedding:RelationEmbedding;

// Remove stale relation embeddings that no longer connect to exactly two entities.
MATCH (embedding:RelationEmbedding)
WITH embedding, size([(embedding)-[:EMBEDS]->(:Entity) | 1]) AS entity_count
WHERE entity_count <> 2
DETACH DELETE embedding;
