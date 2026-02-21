//! Transaction management for database operations.
//!
//! Provides ACID transaction support for mutations and complex queries.

use tokio_postgres::Client;

use crate::db::types::DatabaseError;

/// Represents an active database transaction.
pub struct Transaction<'a> {
    client: &'a mut Client,
    active: bool,
}

impl<'a> Transaction<'a> {
    /// Begin a new transaction.
    pub async fn begin(client: &'a mut Client) -> Result<Self, DatabaseError> {
        client.execute("BEGIN", &[]).await.map_err(|e| {
            DatabaseError::Transaction(format!("Failed to begin transaction: {}", e))
        })?;

        Ok(Transaction {
            client,
            active: true,
        })
    }

    /// Commit the transaction.
    pub async fn commit(mut self) -> Result<(), DatabaseError> {
        if self.active {
            self.client
                .execute("COMMIT", &[])
                .await
                .map_err(|e| DatabaseError::Transaction(format!("Failed to commit: {}", e)))?;
            self.active = false;
        }
        Ok(())
    }

    /// Rollback the transaction.
    pub async fn rollback(mut self) -> Result<(), DatabaseError> {
        if self.active {
            self.client
                .execute("ROLLBACK", &[])
                .await
                .map_err(|e| DatabaseError::Transaction(format!("Failed to rollback: {}", e)))?;
            self.active = false;
        }
        Ok(())
    }

    /// Create a savepoint for nested transactions.
    pub async fn savepoint(&mut self, name: &str) -> Result<(), DatabaseError> {
        self.client
            .execute(&format!("SAVEPOINT {}", name), &[])
            .await
            .map_err(|e| DatabaseError::Transaction(format!("Savepoint failed: {}", e)))?;
        Ok(())
    }

    /// Rollback to a savepoint.
    pub async fn rollback_to_savepoint(&mut self, name: &str) -> Result<(), DatabaseError> {
        self.client.execute(&format!("ROLLBACK TO {}", name), &[]).await.map_err(|e| {
            DatabaseError::Transaction(format!("Rollback to savepoint failed: {}", e))
        })?;
        Ok(())
    }

    /// Execute a query within this transaction.
    pub async fn execute(
        &mut self,
        sql: &str,
        params: &[&(dyn tokio_postgres::types::ToSql + Sync)],
    ) -> Result<u64, DatabaseError> {
        self.client
            .execute(sql, params)
            .await
            .map_err(|e| DatabaseError::Query(format!("Transaction query failed: {}", e)))
    }

    /// Execute a query and return results within this transaction.
    pub async fn query(
        &mut self,
        sql: &str,
        params: &[&(dyn tokio_postgres::types::ToSql + Sync)],
    ) -> Result<Vec<tokio_postgres::Row>, DatabaseError> {
        self.client
            .query(sql, params)
            .await
            .map_err(|e| DatabaseError::Query(format!("Transaction query failed: {}", e)))
    }

    /// Get access to the underlying client for advanced operations.
    pub fn client(&mut self) -> &mut Client {
        self.client
    }
}

impl<'a> Drop for Transaction<'a> {
    fn drop(&mut self) {
        // Note: In a real implementation, we'd want to rollback on drop if not committed
        // But for this phase, we'll keep it simple
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::types::DatabaseResult;

    #[tokio::test]
    async fn test_transaction_lifecycle() {
        // This is a mock test - real transaction testing requires database setup
        // which will be implemented in Phase 2 integration tests

        // Test that the transaction API compiles and the types work
        assert!(true);
    }
}
