# Vulkan Shared Queue Overlap Diagnostics

## Problem

Vulkan offscreen CPU sampling returns `VK_ERROR_DEVICE_LOST` on its first copy submission. Diagnostics show that the graphics and transfer queue wrappers contain the same raw `VkQueue`, while Vulkan requires host access to a queue to be externally synchronized. The existing log proves queue aliasing but does not prove that host calls overlap.

## Objective

Detect whether two tasks enter Vulkan host operations for the same raw `VkQueue` concurrently, without changing queue ordering, adding synchronization, or altering rendering behavior.

## Design

Add a small shared diagnostic state owned by Vulkan queue wrappers. Wrappers that resolve to the same raw `VkQueue` receive the same state when the logical device creates its graphics, transfer, and present queues.

The state records an active host-call count and a monotonically increasing call serial. A scoped diagnostic guard surrounds active `vkQueueSubmit`, `vkQueueWaitIdle`, and `vkQueuePresentKHR` calls. Entry and exit update the active count atomically. If entry observes another active call, it emits an `information(...)` record containing the raw queue handle, operation, serial, active count, task name, command-buffer name, and annotation where available.

Normal non-overlapping operations remain quiet. Existing failure diagnostics remain unchanged.

## Alternatives Considered

- Immediately serialize queue calls: robust if overlap is the cause, but changes behavior before overlap has been demonstrated.
- Use one device-wide queue mutex: simpler, but unnecessarily serializes genuinely distinct Vulkan queues.
- Replace image readback with a staging buffer: potentially more portable, but does not address or test the confirmed queue-aliasing risk.

## Verification

- A focused unit test demonstrates that wrappers for one raw queue share diagnostic state and that overlapping guards are detected.
- The test is observed failing before implementation and passing afterward.
- `gpu_vulkan` compiles through the Visual Studio solution target.
- The application is run with validation enabled. Any `gpu_vulkan queue host overlap` message confirms the host-synchronization defect. If no overlap occurs before the first sampling failure, investigation moves to the recorded sampling command and Windows GPU-timeout evidence.

## Success Criteria

- Diagnostics do not serialize or reorder Vulkan calls.
- No per-frame log is emitted unless host calls overlap.
- Graphics and transfer aliases are correlated by raw `VkQueue`, not merely by wrapper address.
- On-screen and offscreen behavior remain otherwise unchanged.
