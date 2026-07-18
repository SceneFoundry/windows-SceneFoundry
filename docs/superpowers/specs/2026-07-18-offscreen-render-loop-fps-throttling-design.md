# Offscreen Render Loop FPS Throttling Design

## Goal

Bound the CPU-buffer/offscreen graphics3d render loop to a configurable frame rate so it does not consume unbounded CPU time, flood redraw messages, or rapidly increase memory usage when it produces frames faster than the window can consume them.

## Public setting

`graphics3d::engine` will expose a public atomic floating-point setting named `m_fDesiredFps`, initialized to `60.0f`. Callers may assign a new value while the offscreen loop is running. The render thread will load the value once per loop iteration, so a change takes effect without a data race on the following frame.

Non-finite and non-positive values will use the safe 60 FPS default. This prevents an invalid runtime setting from accidentally restoring an unbounded loop.

## Pacing behavior

The offscreen loop will use `std::chrono::steady_clock`, because frame pacing requires a monotonic clock. Each iteration will have an absolute next-frame deadline derived from the desired FPS.

Rendering, GPU-to-CPU readback, and redraw notification time count toward the frame interval. At the end of an iteration, the loop waits only for the unused portion of that interval. Absolute deadlines avoid cumulative drift from repeatedly sleeping for a relative duration.

When an iteration overruns its deadline, the pacer will reset the next deadline from the current time. It will not issue rapid catch-up frames. A runtime FPS change will also reset the deadline using the newly requested interval.

Pacing applies when the engine is rendering and when the current loop iteration cannot render because placement is empty or loading is incomplete. The existing early-continue paths will therefore no longer busy-spin.

The swap-chain path is outside this change; only `run_cpu_buffer()` is paced.

## Structure

Deadline calculation will be kept in a small, independently testable unit rather than embedded throughout rendering code. The unit will accept the current time and desired FPS and return/update the next deadline. Waiting remains in the offscreen loop.

The implementation will preserve the existing frame lifecycle and drawing order. FPS throttling occurs after the iteration's available work and before the next iteration.

## Verification

Deterministic tests will cover:

- the default 60 FPS interval;
- a runtime FPS change resetting the deadline;
- an overrun resetting instead of catching up;
- invalid FPS values selecting 60 FPS;
- a deadline in the future producing a positive wait and an expired deadline producing no wait.

After the tests pass, the affected framework and `shared_app_graphics3d_continuum` Visual Studio targets will be built to verify integration.
