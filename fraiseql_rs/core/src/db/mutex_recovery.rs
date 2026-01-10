//! Mutex poisoning recovery utilities.
//!
//! This module provides graceful recovery mechanisms for poisoned mutexes.
//! When a thread panics while holding a mutex, Rust marks the mutex as "poisoned"
//! to alert other threads. However, in production systems, we want to degrade
//! gracefully rather than crashing the entire server.

use std::sync::{LockResult, MutexGuard};

/// Gracefully recover from a poisoned mutex by extracting the inner value.
///
/// When a mutex is poisoned (i.e., the previous thread that held the lock panicked),
/// we extract the inner value and continue. This allows the system to degrade gracefully
/// instead of panicking and potentially crashing the entire application.
///
/// # Arguments
///
/// * `result` - The `LockResult` from calling `lock()` on a mutex
///
/// # Returns
///
/// The `MutexGuard` allowing access to the inner value, whether the mutex was
/// poisoned or not.
///
/// # Example
///
/// ```ignore
/// use std::sync::Mutex;
/// use crate::db::mutex_recovery::recover_from_poisoned;
///
/// let mutex = Mutex::new(42);
/// let guard = recover_from_poisoned(mutex.lock());
/// assert_eq!(*guard, 42);
/// ```
///
/// # SAFETY
///
/// This function is safe to call. When a mutex is poisoned, we extract the
/// inner value with `into_inner()`, which returns a guard that allows us to
/// access and modify the data. The data itself is not corrupted; only the lock
/// was held by a panicking thread.
///
/// However, calling this function means we're assuming the data protected by
/// the mutex is still in a valid state. If the panicking thread left the data
/// in an inconsistent state, this could lead to subtle bugs. For this reason,
/// we log a warning when poisoning occurs.
pub fn recover_from_poisoned<T>(result: LockResult<MutexGuard<'_, T>>) -> MutexGuard<'_, T> {
    match result {
        Ok(guard) => guard,
        Err(poisoned) => {
            eprintln!(
                "WARNING: Mutex was poisoned (previous thread panicked while holding the lock). \
                 Recovering by extracting the inner value. If subsequent operations fail, \
                 the protected data may be in an inconsistent state."
            );
            poisoned.into_inner()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    #[test]
    fn test_recovery_from_non_poisoned_mutex() {
        let mutex = Arc::new(Mutex::new(42));
        let guard = recover_from_poisoned(mutex.lock());
        assert_eq!(*guard, 42);
    }

    #[test]
    fn test_recovery_from_poisoned_mutex() {
        let mutex = Arc::new(Mutex::new(vec![1, 2, 3]));
        let mutex_clone = Arc::clone(&mutex);

        // Simulate a panic while holding the lock
        let handle = std::thread::spawn(move || {
            let _guard = mutex_clone.lock().unwrap();
            panic!("Simulated panic in critical section");
        });

        // Wait for panic and thread to finish
        let _ = handle.join();

        // Now try to recover from poisoned mutex
        let result = mutex.lock();
        assert!(result.is_err(), "Mutex should be poisoned after panic");

        // But recovery should work
        let guard = recover_from_poisoned(result);
        assert_eq!(guard.len(), 3);

        // And we should be able to modify the data
        drop(guard);
        let mut new_guard = recover_from_poisoned(mutex.lock());
        new_guard.push(4);
        drop(new_guard);

        // Verify modification worked
        let final_guard = recover_from_poisoned(mutex.lock());
        assert_eq!(final_guard.len(), 4);
    }

    #[test]
    fn test_poisoned_mutex_with_string_data() {
        let mutex = Arc::new(Mutex::new(String::from("initial")));
        let mutex_clone = Arc::clone(&mutex);

        let handle = std::thread::spawn(move || {
            let _guard = mutex_clone.lock().unwrap();
            panic!("Simulated panic");
        });

        let _ = handle.join();

        // Recover from poisoning
        let guard = recover_from_poisoned(mutex.lock());
        assert_eq!(guard.as_str(), "initial");
    }

    #[test]
    fn test_multiple_recovery_attempts() {
        let mutex = Arc::new(Mutex::new(0u32));
        let mutex_clone = Arc::clone(&mutex);

        // First panic
        let handle1 = std::thread::spawn(move || {
            let _guard = mutex_clone.lock().unwrap();
            panic!("First panic");
        });
        let _ = handle1.join();

        // First recovery
        let mut guard = recover_from_poisoned(mutex.lock());
        *guard = 100;
        drop(guard);

        // The mutex is now "recovered" and subsequent operations should work normally
        let second_lock = mutex.lock();
        assert!(
            second_lock.is_err(),
            "Mutex is still marked as poisoned after first recovery"
        );

        // But we can still recover again
        let final_guard = recover_from_poisoned(second_lock);
        assert_eq!(*final_guard, 100);
    }

    #[test]
    fn test_recovery_preserves_data_after_poison() {
        let mutex = Arc::new(Mutex::new(vec![1, 2, 3]));
        let mutex_clone = Arc::clone(&mutex);

        // Simulate a panic while holding the lock
        let handle = std::thread::spawn(move || {
            let _guard = mutex_clone.lock().unwrap();
            panic!("Simulated panic in critical section");
        });

        // Wait for panic and thread to finish
        let _ = handle.join();

        // Verify we can recover and data is intact
        let guard = recover_from_poisoned(mutex.lock());
        assert_eq!(guard.len(), 3);
    }
}
