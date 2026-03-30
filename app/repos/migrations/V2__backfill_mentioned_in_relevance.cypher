MATCH ()-[rel:MENTIONED_IN]->()
WHERE rel.relevance IS NULL
SET rel.relevance = 0.5;
