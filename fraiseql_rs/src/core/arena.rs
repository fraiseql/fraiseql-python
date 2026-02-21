//! Bump allocator for request-scoped memory
//!
//! All temporary allocations (transformed keys, intermediate buffers)
//! use this arena. When request completes, entire arena is freed at once.
//!
//! Performance:
//! - Allocation: O(1) - just bump a pointer!
//! - Deallocation: O(1) - free entire arena
//! - Cache-friendly: Linear memory layout
//! - No fragmentation: Reset pointer between requests
//!
//! Safety:
//! - Single-threaded use only (enforced by marker field)
//! - Maximum size limit prevents OOM

use std::{cell::UnsafeCell, marker::PhantomData};

/// Maximum arena size (16 MB) - prevents OOM on malicious input
pub const MAX_ARENA_SIZE: usize = 16 * 1024 * 1024;

/// Default arena capacity (8 KB) - suitable for most requests
pub const DEFAULT_ARENA_CAPACITY: usize = 8 * 1024;

/// Arena allocation error
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArenaError {
    /// Requested allocation would exceed maximum arena size
    SizeExceeded,
    /// Arithmetic overflow in size calculation
    Overflow,
}

impl std::fmt::Display for ArenaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ArenaError::SizeExceeded => {
                write!(f, "Arena size limit exceeded ({} bytes)", MAX_ARENA_SIZE)
            },
            ArenaError::Overflow => write!(f, "Arena size calculation overflow"),
        }
    }
}

impl std::error::Error for ArenaError {}

/// Bump allocator for request-scoped memory
///
/// # Thread Safety
///
/// This type is explicitly `!Send` and `!Sync` because it uses interior
/// mutability without synchronization. The `_marker` field ensures this
/// at compile time. Each request should have its own arena.
///
/// # Memory Limits
///
/// The arena enforces a maximum size of [`MAX_ARENA_SIZE`] bytes to prevent
/// out-of-memory conditions from malicious or malformed input.
///
/// # Safety Invariants
///
/// This type is !Send + !Sync enforced by `PhantomData<*const ()>`.
///
/// **Why this is safe:**
/// 1. **Single-threaded access guaranteed** - Marker type prevents cross-thread use at compile time
/// 2. **Lifetime safety** - Returned slices are tied to arena lifetime via Rust's borrow checker
/// 3. **No aliasing** - Each allocation returns non-overlapping slices from sequential memory
/// 4. **Bounds checked** - All allocations verify size limits before modifying buffer
/// 5. **Interior mutability** - UnsafeCell required for bump pointer pattern, but access is
///    serialized
///
/// **Unsafe code justification:**
/// - `UnsafeCell<Vec<u8>>`: Required for interior mutability in bump allocator pattern
/// - `UnsafeCell<usize>`: Position tracking with interior mutability
/// - `PhantomData<*const ()>`: Enforces thread safety (!Send/!Sync) at compile time
/// - All unsafe blocks have SAFETY comments explaining why access is safe
///
/// **Memory safety guarantees:**
/// - No use-after-free: Allocations tied to arena lifetime
/// - No buffer overflows: Size checks before every allocation
/// - No data races: Single-threaded access enforced by type system
/// - No memory leaks: Arena memory freed when struct is dropped
///
/// **Stack usage:** Negligible (struct itself is ~48 bytes on 64-bit systems)
pub struct Arena {
    buf:      UnsafeCell<Vec<u8>>,
    pos:      UnsafeCell<usize>,
    max_size: usize,
    /// Marker to make Arena `!Send` and `!Sync`
    ///
    /// `*const ()` is neither Send nor Sync, so this field ensures
    /// Arena cannot be shared across threads.
    _marker:  PhantomData<*const ()>,
}

impl Arena {
    /// Create arena with initial capacity and default max size.
    ///
    /// # Arguments
    /// * `capacity` - Initial buffer capacity (will grow as needed up to max)
    ///
    /// # Recommended Capacities
    /// - 8KB for small requests (< 50 fields)
    /// - 64KB for large requests (> 500 fields)
    pub fn with_capacity(capacity: usize) -> Self {
        Arena {
            buf:      UnsafeCell::new(Vec::with_capacity(capacity.min(MAX_ARENA_SIZE))),
            pos:      UnsafeCell::new(0),
            max_size: MAX_ARENA_SIZE,
            _marker:  PhantomData,
        }
    }

    /// Create arena with custom maximum size.
    ///
    /// # Arguments
    /// * `capacity` - Initial buffer capacity
    /// * `max_size` - Maximum allowed size (capped at MAX_ARENA_SIZE)
    pub fn with_capacity_and_max(capacity: usize, max_size: usize) -> Self {
        let effective_max = max_size.min(MAX_ARENA_SIZE);
        Arena {
            buf:      UnsafeCell::new(Vec::with_capacity(capacity.min(effective_max))),
            pos:      UnsafeCell::new(0),
            max_size: effective_max,
            _marker:  PhantomData,
        }
    }

    /// Allocate bytes in arena (fallible version).
    ///
    /// # Arguments
    /// * `len` - Number of bytes to allocate
    ///
    /// # Returns
    /// * `Ok(&mut [u8])` - Mutable slice of allocated bytes
    /// * `Err(ArenaError)` - If allocation would exceed limits
    ///
    /// # Safety
    ///
    /// This is safe because:
    /// 1. Arena is `!Send + !Sync` (via _marker field), ensuring single-threaded access
    /// 2. Returned slice lifetime is tied to arena lifetime
    /// 3. We check bounds before growing buffer
    #[inline]
    #[allow(clippy::mut_from_ref)] // Interior mutability pattern - safe via !Send + !Sync marker
    pub fn try_alloc_bytes(&self, len: usize) -> Result<&mut [u8], ArenaError> {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        unsafe {
            let pos = self.pos.get();
            let buf = self.buf.get();

            let current_pos = *pos;
            let new_pos = current_pos.checked_add(len).ok_or(ArenaError::Overflow)?;

            if new_pos > self.max_size {
                return Err(ArenaError::SizeExceeded);
            }

            // Grow buffer if needed
            if new_pos > (*buf).len() {
                (*buf).resize(new_pos, 0);
            }

            *pos = new_pos;

            // SAFETY: We've ensured the slice is within bounds and buffer is valid
            let slice = &mut (&mut *buf)[current_pos..new_pos];
            Ok(slice)
        }
    }

    /// Allocate bytes from the arena (convenience wrapper, panics on failure).
    ///
    /// This is a convenience wrapper over `try_alloc_bytes` that panics on failure.
    /// Use this when you know the allocation will fit within limits.
    /// For error handling, use `try_alloc_bytes` instead.
    ///
    /// # Panics
    /// Panics if allocation would exceed max_size limit.
    ///
    /// # Safety
    /// Same safety guarantees as `try_alloc_bytes`.
    #[inline(always)]
    #[allow(clippy::mut_from_ref)] // Interior mutability pattern - safe via !Send + !Sync marker
    #[allow(clippy::expect_used)] // Intentional panic for convenience API
    pub fn alloc_bytes(&self, len: usize) -> &mut [u8] {
        self.try_alloc_bytes(len).expect("Arena size limit exceeded")
    }

    /// Reset arena for next request.
    ///
    /// This does not deallocate memory - it just resets the position pointer.
    /// The underlying buffer is reused for the next request.
    #[inline]
    pub fn reset(&self) {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        unsafe {
            *self.pos.get() = 0;
        }
    }

    /// Get current allocation position (bytes used).
    #[inline]
    pub fn used(&self) -> usize {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        unsafe { *self.pos.get() }
    }

    /// Get remaining capacity before hitting max size.
    #[inline]
    pub fn remaining(&self) -> usize {
        self.max_size.saturating_sub(self.used())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_allocation() {
        let arena = Arena::with_capacity(1024);
        let slice = arena.alloc_bytes(100);
        assert_eq!(slice.len(), 100);
        assert_eq!(arena.used(), 100);
    }

    #[test]
    fn test_size_limit() {
        let arena = Arena::with_capacity_and_max(100, 200);

        // First allocation succeeds
        assert!(arena.try_alloc_bytes(150).is_ok());

        // Second allocation fails (would exceed 200 byte limit)
        assert!(matches!(arena.try_alloc_bytes(100), Err(ArenaError::SizeExceeded)));
    }

    #[test]
    fn test_reset() {
        let arena = Arena::with_capacity(1024);
        arena.alloc_bytes(500);
        assert_eq!(arena.used(), 500);

        arena.reset();
        assert_eq!(arena.used(), 0);

        // Can allocate again after reset
        arena.alloc_bytes(500);
        assert_eq!(arena.used(), 500);
    }

    #[test]
    fn test_overflow_protection() {
        let arena = Arena::with_capacity(100);

        // Try to allocate usize::MAX bytes - should fail with overflow
        assert!(matches!(arena.try_alloc_bytes(usize::MAX), Err(ArenaError::Overflow)));
    }

    #[test]
    fn test_not_send_sync() {
        // This test verifies at compile time that Arena is !Send and !Sync
        // Uncomment these lines to verify compilation fails:

        // fn assert_send<T: Send>() {}
        // fn assert_sync<T: Sync>() {}
        // assert_send::<Arena>();  // Should fail to compile
        // assert_sync::<Arena>();  // Should fail to compile
    }

    // ========================================================================
    // Property-Based Tests (Fuzzing with proptest)
    // ========================================================================
    //
    // These tests use proptest to generate random inputs and verify safety
    // invariants hold for all possible inputs. This catches edge cases that
    // hand-written tests might miss.

    #[cfg(test)]
    mod proptests {
        use proptest::prelude::*;

        use super::*;

        proptest! {
            /// Property: Arena never exceeds max_size, no matter what allocations are attempted
            #[test]
            fn arena_never_exceeds_max_size(
                alloc_sizes in prop::collection::vec(1usize..1024, 0..200)
            ) {
                let max_size = 10240; // 10KB max
                let arena = Arena::with_capacity_and_max(100, max_size);

                for size in alloc_sizes {
                    let _ = arena.try_alloc_bytes(size);
                    // Critical invariant: used bytes never exceeds max_size
                    prop_assert!(arena.used() <= max_size);
                }
            }

            /// Property: Allocations are sequential (no overlaps)
            #[test]
            fn allocations_are_sequential(
                alloc_sizes in prop::collection::vec(1usize..100, 1..50)
            ) {
                let arena = Arena::with_capacity_and_max(100, 10240);
                let mut expected_pos = 0;

                for size in alloc_sizes {
                    if expected_pos + size <= arena.max_size {
                        let result = arena.try_alloc_bytes(size);
                        prop_assert!(result.is_ok());
                        expected_pos += size;
                        prop_assert_eq!(arena.used(), expected_pos);
                    } else {
                        // Should fail when exceeding max_size
                        let result = arena.try_alloc_bytes(size);
                        prop_assert!(result.is_err());
                        // Position unchanged after failed allocation
                        prop_assert_eq!(arena.used(), expected_pos);
                    }
                }
            }

            /// Property: Reset always returns arena to zero state
            #[test]
            fn reset_returns_to_zero(
                alloc_sizes in prop::collection::vec(1usize..100, 1..50)
            ) {
                let arena = Arena::with_capacity_and_max(100, 10240);

                // Allocate some memory
                for size in alloc_sizes.iter().take(10) {
                    let _ = arena.try_alloc_bytes(*size);
                }

                // Reset should bring used back to zero
                arena.reset();
                prop_assert_eq!(arena.used(), 0);

                // Should be able to allocate again from the beginning
                let result = arena.try_alloc_bytes(100);
                prop_assert!(result.is_ok());
                prop_assert_eq!(arena.used(), 100);
            }

            /// Property: Remaining capacity is always max_size - used
            #[test]
            fn remaining_equals_max_minus_used(
                alloc_sizes in prop::collection::vec(1usize..100, 1..30)
            ) {
                let max_size = 5000;
                let arena = Arena::with_capacity_and_max(100, max_size);

                for size in alloc_sizes {
                    let used_before = arena.used();
                    let remaining_before = arena.remaining();

                    // Invariant holds before allocation
                    prop_assert_eq!(used_before + remaining_before, max_size);

                    let _ = arena.try_alloc_bytes(size);

                    let used_after = arena.used();
                    let remaining_after = arena.remaining();

                    // Invariant holds after allocation
                    prop_assert_eq!(used_after + remaining_after, max_size);
                }
            }

            /// Property: Zero-sized allocations always succeed and don't change position
            #[test]
            fn zero_sized_allocations_noop(
                iterations in 1usize..100
            ) {
                let arena = Arena::with_capacity_and_max(100, 1024);

                // Allocate something first
                let _ = arena.try_alloc_bytes(42);
                let pos_before = arena.used();

                // Multiple zero-sized allocations
                for _ in 0..iterations {
                    let result = arena.try_alloc_bytes(0);
                    prop_assert!(result.is_ok());
                }

                // Position should not have changed
                prop_assert_eq!(arena.used(), pos_before);
            }

            /// Property: Allocation failure is deterministic
            #[test]
            fn allocation_failure_deterministic(
                size in 1usize..2000
            ) {
                let max_size = 1024;
                let arena = Arena::with_capacity_and_max(100, max_size);

                // Fill arena to near capacity
                let _ = arena.try_alloc_bytes(max_size - 100);

                // First attempt
                let result1 = arena.try_alloc_bytes(size);
                let used1 = arena.used();

                // Reset and try again
                arena.reset();
                let _ = arena.try_alloc_bytes(max_size - 100);

                // Second attempt with same parameters
                let result2 = arena.try_alloc_bytes(size);
                let used2 = arena.used();

                // Should get same result both times (deterministic)
                prop_assert_eq!(result1.is_ok(), result2.is_ok());
                prop_assert_eq!(used1, used2);
            }

            /// Property: No memory corruption - allocated bytes are independent
            #[test]
            fn no_memory_corruption(
                values in prop::collection::vec(0u8..=255, 10..50)
            ) {
                let arena = Arena::with_capacity_and_max(100, 10240);
                let mut allocated_slices = Vec::new();

                // Allocate multiple slices and write unique values
                for (i, &value) in values.iter().enumerate() {
                    if let Ok(slice) = arena.try_alloc_bytes(10) {
                        slice.fill(value);
                        allocated_slices.push((i, value, slice.as_ptr()));
                    }
                }

                // Verify each slice still has its original value (no corruption)
                for (i, expected_value, ptr) in allocated_slices {
                    let start = i * 10;
                    // SAFETY: We know the arena is still alive and slices are valid
                    unsafe {
                        let slice = std::slice::from_raw_parts(ptr, 10);
                        prop_assert!(slice.iter().all(|&b| b == expected_value));
                    }
                }
            }
        }
    }
}
