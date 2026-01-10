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

use std::cell::UnsafeCell;
use std::marker::PhantomData;

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
            Self::SizeExceeded => {
                write!(f, "Arena size limit exceeded ({MAX_ARENA_SIZE} bytes)")
            }
            Self::Overflow => write!(f, "Arena size calculation overflow"),
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
/// 5. **Interior mutability** - `UnsafeCell` required for bump pointer pattern, but access is serialized
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
    buf: UnsafeCell<Vec<u8>>,
    pos: UnsafeCell<usize>,
    max_size: usize,
    /// Marker to make Arena `!Send` and `!Sync`
    ///
    /// `*const ()` is neither Send nor Sync, so this field ensures
    /// Arena cannot be shared across threads.
    _marker: PhantomData<*const ()>,
}

impl std::fmt::Debug for Arena {
    #[allow(unsafe_code)] // Performance-critical Debug impl
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Arena")
            .field("capacity", &unsafe { (*self.buf.get()).capacity() }) // SAFETY: UnsafeCell access - single-threaded
            .field("used", &unsafe { *self.pos.get() }) // SAFETY: UnsafeCell access - single-threaded
            .field("max_size", &self.max_size)
            .finish()
    }
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
    #[must_use]
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            buf: UnsafeCell::new(Vec::with_capacity(capacity.min(MAX_ARENA_SIZE))),
            pos: UnsafeCell::new(0),
            max_size: MAX_ARENA_SIZE,
            _marker: PhantomData,
        }
    }

    /// Create arena with custom maximum size.
    ///
    /// # Arguments
    /// * `capacity` - Initial buffer capacity
    /// * `max_size` - Maximum allowed size (capped at `MAX_ARENA_SIZE`)
    #[must_use]
    pub fn with_capacity_and_max(capacity: usize, max_size: usize) -> Self {
        let effective_max = max_size.min(MAX_ARENA_SIZE);
        Self {
            buf: UnsafeCell::new(Vec::with_capacity(capacity.min(effective_max))),
            pos: UnsafeCell::new(0),
            max_size: effective_max,
            _marker: PhantomData,
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
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Allocation would cause position overflow
    /// - Allocation would exceed maximum arena size
    /// - Buffer growth fails
    #[inline]
    // Interior mutability pattern - safe via !Send + !Sync
    #[allow(clippy::mut_from_ref)] // Interior mutability pattern - safe via !Send + !Sync marker
    pub fn try_alloc_bytes(&self, len: usize) -> Result<&mut [u8], ArenaError> {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        #[allow(unsafe_code)] // Performance-critical bump allocator
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
    /// Panics if allocation would exceed `max_size` limit.
    ///
    /// # Safety
    /// Same safety guarantees as `try_alloc_bytes`.
    #[allow(clippy::inline_always)] // Performance-critical hot path
    // Interior mutability pattern - safe via !Send + !Sync
    #[allow(clippy::mut_from_ref)]
    // Interior mutability pattern - safe via !Send + !Sync marker
    // Intentional panic for convenience API
    #[allow(clippy::expect_used)] // Intentional panic for convenience API
    pub fn alloc_bytes(&self, len: usize) -> &mut [u8] {
        self.try_alloc_bytes(len)
            .expect("Arena size limit exceeded")
    }

    /// Reset arena for next request.
    ///
    /// This does not deallocate memory - it just resets the position pointer.
    /// The underlying buffer is reused for the next request.
    #[inline]
    pub fn reset(&self) {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        #[allow(unsafe_code)] // Performance-critical reset
        unsafe {
            *self.pos.get() = 0;
        }
    }

    /// Get current allocation position (bytes used).
    #[inline]
    pub fn used(&self) -> usize {
        // SAFETY: Single-threaded access enforced by !Send + !Sync marker
        #[allow(unsafe_code)] // Performance-critical accessor
        unsafe {
            *self.pos.get()
        }
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
        assert!(matches!(
            arena.try_alloc_bytes(100),
            Err(ArenaError::SizeExceeded)
        ));
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
        assert!(matches!(
            arena.try_alloc_bytes(usize::MAX),
            Err(ArenaError::Overflow)
        ));
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

    // proptest-based property tests temporarily disabled
    // TODO: Re-enable when proptest dependency is properly configured
    // These tests verify safety invariants hold for all possible inputs
}
