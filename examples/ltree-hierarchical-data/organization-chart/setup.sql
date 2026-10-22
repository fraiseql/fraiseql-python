-- Organization Chart LTREE Example
-- Each employee's org_path is the chain of managers down to them, so the
-- hierarchy queries are ltree comparisons on one indexed column.

CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TABLE tb_employee (
    pk_employee INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT NOT NULL,
    org_path LTREE UNIQUE NOT NULL,  -- e.g. alice.bob.david: alice manages bob, who manages david
    hire_date DATE NOT NULL
);

-- GiST index for ancestor/descendant queries
CREATE INDEX idx_tb_employee_org_path ON tb_employee USING GIST (org_path);

-- The view fraiseql reads: filterable columns, plus the object as JSONB
CREATE VIEW v_employee AS
SELECT
    id,
    org_path,
    nlevel(org_path) AS level,
    department,
    jsonb_build_object(
        'id', id,
        'name', name,
        'title', title,
        'department', department,
        'org_path', org_path::text,
        'level', nlevel(org_path),
        'hire_date', hire_date
    ) AS data
FROM tb_employee;

INSERT INTO tb_employee (name, title, department, org_path, hire_date) VALUES
('Alice Johnson', 'CEO', 'Executive', 'alice', '2020-01-01'),
('Bob Smith', 'CTO', 'Technology', 'alice.bob', '2020-02-01'),
('Carol Davis', 'CFO', 'Finance', 'alice.carol', '2020-03-01'),
('Liam Johnson', 'VP Product', 'Product', 'alice.liam', '2020-10-01'),
('David Wilson', 'VP Engineering', 'Engineering', 'alice.bob.david', '2020-04-01'),
('Eva Garcia', 'Backend Manager', 'Engineering', 'alice.bob.david.eva', '2020-05-01'),
('Frank Miller', 'Senior Engineer', 'Engineering', 'alice.bob.david.eva.frank', '2020-06-01'),
('Grace Lee', 'Senior Engineer', 'Engineering', 'alice.bob.david.eva.grace', '2020-07-01'),
('Henry Taylor', 'Junior Engineer', 'Engineering', 'alice.bob.david.eva.henry', '2021-01-01'),
('Ivy Chen', 'Frontend Manager', 'Engineering', 'alice.bob.david.ivy', '2020-08-01'),
('Jack Brown', 'Frontend Developer', 'Engineering', 'alice.bob.david.ivy.jack', '2020-09-01'),
('Mia Rodriguez', 'Product Manager', 'Product', 'alice.liam.mia', '2020-11-01'),
('Noah Martinez', 'Associate PM', 'Product', 'alice.liam.mia.noah', '2021-03-01'),
('Paula Kim', 'Accountant', 'Finance', 'alice.carol.paula', '2021-04-01');

ANALYZE tb_employee;
