---
title: Troubleshooting Guide
description: Common issues, solutions, and debugging strategies
tags:
  - troubleshooting
  - debugging
  - errors
  - solutions
  - problems
---

# Troubleshooting Guide

Common issues and solutions for FraiseQL beginners.

**💡 Quick Navigation:**

- **[Troubleshooting Decision Tree](troubleshooting-decision-tree.md)** - Diagnose issues by category (Installation, Database, Performance, Deployment, etc.)
- **This guide** - Specific error messages and detailed solutions

Can't find your issue? Check the [GitHub Issues](../issues) or ask in [Discussions](../discussions).

## "View not found" error

**Symptom**: `ERROR: relation "v_note" does not exist`

**Cause**: Database schema not created or incomplete

**Solution**:

```bash
# Check if your database exists
psql -l | grep your_database_name

# If not, create it
createdb your_database_name

# Load your schema
psql your_database_name < schema.sql

# Verify views exist
psql your_database_name -c "\dv v_*"
```

**Prevention**: Always run schema setup before starting your app

---

## "Module fraiseql not found"

**Symptom**: `ModuleNotFoundError: No module named 'fraiseql'`

**Cause**: FraiseQL not installed or virtual environment issue

**Solution**:

```bash
# Install FraiseQL
pip install "fraiseql[all]<2"

# Or if using uv
uv add "fraiseql<2"

# Verify installation
python -c "import fraiseql; print('FraiseQL installed!')"
```

**Prevention**: Use virtual environments and check `pip list | grep fraiseql`

---

## "Connection refused" to PostgreSQL

**Symptom**: `asyncpg.exceptions.ConnectionDoesNotExistError: Connection refused`

**Cause**: PostgreSQL not running or connection parameters wrong

**Solution**:

```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list | grep postgres  # macOS

# Start PostgreSQL if needed
sudo systemctl start postgresql  # Linux
brew services start postgresql   # macOS

# Test connection
psql -h localhost -U postgres -d postgres

# Check your connection string in app.py
# Should be: "postgresql://user:password@localhost:5432/dbname"
```

**Prevention**: Use `pg_isready -h localhost` to test connectivity

---

## "Type X does not match database"

**Symptom**: `ValidationError: Type 'Note' field 'id' type mismatch`

**Cause**: Python type doesn't match database view structure

**Solution**:

```python
import fraiseql
from fraiseql.types import ID

# Check your view definition
psql your_db -c "SELECT * FROM v_note LIMIT 1;"

# Compare with Python type
@type(sql_source="v_note")
class Note:
    id: ID        # Must match database column type
    title: str      # Must match database column type
    content: str    # Must match database column type
```

**Prevention**: Keep Python types and database views in sync

---

## GraphQL Playground not loading

**Symptom**: Browser shows blank page or connection error at `/graphql`

**Cause**: Server not running or wrong endpoint

**Solution**:

```bash
# Check server is running
curl http://localhost:8000/graphql

# Check your FastAPI setup
from fastapi import FastAPI
from fraiseql.fastapi import FraiseQLRouter

app = FastAPI()
router = FraiseQLRouter(repo=repo, schema=fraiseql.build_schema())
app.include_router(router, prefix="/graphql")  # This creates /graphql endpoint

# Run server
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

**Prevention**: Visit `http://localhost:8000/docs` for FastAPI docs, `http://localhost:8000/graphql` for GraphQL playground

---

## Queries return empty results

**Symptom**: GraphQL queries succeed but return empty arrays

**Cause**: No data in database or view not returning data

**Solution**:

```bash
# Check table has data
psql your_db -c "SELECT COUNT(*) FROM tb_note;"

# Check view returns data
psql your_db -c "SELECT * FROM v_note;"

# If view is empty, check view definition
psql your_db -c "\d+ v_note;"

# Add sample data
psql your_db -c "INSERT INTO tb_note (title, content) VALUES ('Test', 'Content');"
```

**Prevention**: Always populate test data after schema creation

---

## "Permission denied" for database

**Symptom**: `psycopg2.OperationalError: FATAL: permission denied for database`

**Cause**: Database user lacks permissions

**Solution**:

```bash
# Create user with permissions
psql -U postgres -c "CREATE USER myuser WITH PASSWORD 'mypass';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE mydb TO myuser;"

# Or use postgres user
# Connection string: "postgresql://postgres:password@localhost:5432/mydb"
```

**Prevention**: Use database superuser for development

---

## "Column X does not exist"

**Symptom**: `ERROR: column "tags" does not exist`

**Cause**: Database schema not updated after adding fields

**Solution**:

```bash
# Add the missing column
psql your_db -c "ALTER TABLE tb_note ADD COLUMN tags TEXT[] DEFAULT '{}';"

# Update the view
psql your_db -c "DROP VIEW v_note;"
psql your_db -c "CREATE VIEW v_note AS SELECT jsonb_build_object('id', id, 'title', title, 'content', content, 'tags', tags) as data FROM tb_note;"

# Restart your Python app
```

**Prevention**: Keep schema migrations version controlled

---

## "Function does not exist"

**Symptom**: `ERROR: function fn_delete_note(uuid) does not exist`

**Cause**: Database function not created

**Solution**:

```sql
-- Create the missing function
CREATE OR REPLACE FUNCTION fn_delete_note(note_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM tb_note WHERE pk_note = note_id;
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;
```

**Prevention**: Run all schema files in order

---

## "No such file or directory" for schema.sql

**Symptom**: `psql: could not open file "schema.sql": No such file or directory`

**Cause**: Schema file not in current directory or wrong path

**Solution**:

```bash
# Find your schema file
find . -name "schema.sql"

# Use absolute path
psql mydb < /full/path/to/schema.sql

# Or cd to the directory first
cd examples/quickstart_5min
psql mydb < schema.sql
```

**Prevention**: Check file exists with `ls -la schema.sql`

---

## Import errors in Python

**Symptom**: `ImportError: cannot import name 'type' from 'fraiseql'`

**Cause**: Wrong import syntax or FraiseQL version issue

**Solution**:

```python
# Correct imports for current version
import fraiseql

# Not these (old/incorrect):
# import fraiseql
# import fraiseql as fq; fq.type
```


---

## Server won't start

**Symptom**: `uvicorn app:app --reload` fails or exits immediately

**Cause**: Python syntax error or missing dependencies

**Solution**:

```bash
# Check Python syntax
python -m py_compile app.py

# Check imports work
python -c "import app; print('App imports OK')"

# Run with verbose output
uvicorn app:app --reload --log-level debug

# Check port not in use
lsof -i :8000
```

**Prevention**: Test imports with `python -c "import app"` before running

---

## Need More Help?

### Debug Checklist

1. ✅ PostgreSQL is running: `pg_isready -h localhost`
2. ✅ Database exists: `psql -l | grep your_db`
3. ✅ Schema loaded: `psql your_db -c "\dt tb_*"` and `psql your_db -c "\dv v_*"`
4. ✅ Python app imports: `python -c "import app"`
5. ✅ Server starts: `uvicorn app:app --reload`
6. ✅ GraphQL endpoint responds: `curl http://localhost:8000/graphql`

### Getting Help

- 📖 Check the [First Hour Guide](../getting-started/first-hour.md) for step-by-step help
- 🔍 Search [existing issues](../issues)
- 💬 Ask in [GitHub Discussions](../discussions)
- 📧 File a [new issue](https://github.com/fraiseql/fraiseql/issues/new) with your error message

### Common Next Steps

- [Quick Reference](../reference/quick-reference.md) - Copy-paste code patterns
- Examples (../../examples/) - Working applications you can study
- [Beginner Learning Path](../tutorials/beginner-path.md) - Complete skill progression
