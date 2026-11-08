-- Simple notes table

CREATE TABLE tb_note (

    id SERIAL PRIMARY KEY,

    title VARCHAR(200) NOT NULL,

    content TEXT,

    created_at TIMESTAMP DEFAULT NOW()

);

-- Notes view for GraphQL queries

CREATE VIEW v_note AS

SELECT

    id,

    jsonb_build_object(

        'id', id,

        'title', title,

        'content', content,

        'created_at', created_at

    ) AS data

FROM tb_note;

-- What a mutation function returns: fraiseql reads these 8 fields
-- (migrations/trinity/005_add_mutation_response.sql defines it too, with helpers)
CREATE TYPE mutation_response AS (
    status text, message text, entity_id text, entity_type text,
    entity jsonb, updated_fields text[], cascade jsonb, metadata jsonb
);

-- SQL function for creating notes (CQRS pattern): the CreateNote mutation calls it
-- with the input as one jsonb
CREATE OR REPLACE FUNCTION create_note(input jsonb)
RETURNS mutation_response AS $$
DECLARE
    new_id int;
BEGIN
    INSERT INTO tb_note (title, content)
    VALUES (input->>'title', input->>'content')
    RETURNING id INTO new_id;

    RETURN ROW('new', 'Note created', new_id::text, 'Note',
               (SELECT data FROM v_note WHERE id = new_id),
               NULL, NULL, NULL)::mutation_response;
END;
$$ LANGUAGE plpgsql;

-- Sample data

INSERT INTO tb_note (title, content) VALUES

    ('Welcome to FraiseQL', 'This is your first note!'),

    ('GraphQL is awesome', 'Queries and mutations made simple'),

    ('Database-first design', 'Views compose data for optimal performance');
