-- Vector Search Example Schema
-- Demonstrates the six pgvector distance operators

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table with vector embeddings and binary hashes
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384),  -- Text embedding (e.g., all-MiniLM-L6-v2)
    binary_hash bit(64),   -- Binary hash for Hamming/Jaccard (64-bit)
    category TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON documents (category);
CREATE INDEX ON documents (created_at);

-- Stand-in embedding: a deterministic 384-dimension vector per seed. Replace
-- it with your embedding model's output.
CREATE FUNCTION sample_embedding(seed float) RETURNS vector AS $$
    SELECT array_agg(round(sin(i * 0.05 + seed)::numeric, 3)::float4 ORDER BY i)::vector(384)
    FROM generate_series(1, 384) AS i;
$$ LANGUAGE sql IMMUTABLE;

-- Sample data
INSERT INTO documents (title, content, embedding, binary_hash, category) VALUES
(
  'Machine Learning Basics',
  'Introduction to machine learning concepts, algorithms, and applications in modern computing.',
  sample_embedding(0.0),
  B'1010101010101010101010101010101010101010101010101010101010101010',
  'technical'
),
(
  'Deep Learning Guide',
  'Advanced neural network techniques, transformers, and modern AI architectures.',
  sample_embedding(0.2),
  B'1010101010101010101010101010101010101010101010101010101010101011',
  'technical'
),
(
  'Web Development Fundamentals',
  'HTML, CSS, JavaScript basics for building modern web applications.',
  sample_embedding(1.5),
  B'1100110011001100110011001100110011001100110011001100110011001100',
  'technical'
),
(
  'Sourdough at Home',
  'Starter, hydration and baking times for a first loaf.',
  sample_embedding(3.0),
  B'0000000011111111000000001111111100000000111111110000000011111111',
  'cooking'
);
