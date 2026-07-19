# Vulkan Shared Queue Overlap Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect overlapping Vulkan host calls made through different wrappers that refer to the same raw `VkQueue`, without changing queue ordering or synchronization.

**Architecture:** A standard-C++ helper owns a registry keyed by raw queue identity and an atomic active-call counter for each identity. Vulkan queue wrappers obtain shared diagnostic state from the registry, while a scoped guard around submit, wait-idle, and present calls emits `information(...)` only when the active count proves overlap.

**Tech Stack:** C++20, Vulkan 1.4, SceneFoundry `information(...)`, Visual Studio/MSBuild, standalone assertion-based regression tests.

## Global Constraints

- Preserve existing user changes and do not commit the dirty workspace.
- Preserve CRLF line endings in modified Windows source files.
- Diagnostics must not serialize, delay, retry, or reorder Vulkan calls.
- Correlate wrappers by raw `VkQueue`, not by wrapper address.
- Emit no routine per-frame message when calls do not overlap.

---

### Task 1: Pure shared-state and overlap detector

**Files:**
- Create: `source/app-graphics3d/gpu_vulkan/queue_host_call_diagnostics.h`
- Create: `source/app-graphics3d/gpu_vulkan/tests/queue_host_call_diagnostics_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj`
- Modify: `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj.filters`

**Interfaces:**
- Produces: `queue_host_call_diagnostic_registry::state_for(std::uintptr_t)` returning shared state for a raw queue identity.
- Produces: `enter_queue_host_call(queue_host_call_diagnostic_state&)` and `leave_queue_host_call(queue_host_call_diagnostic_state&)`.

- [ ] **Step 1: Write the failing standalone test**

The test requests state twice for key `0x1000`, once for `0x2000`, and asserts that equal keys share state while different keys do not. It then enters twice without leaving and asserts active counts `1` and `2`, serials `1` and `2`, and overlap only on the second entry. Finally it leaves twice and asserts remaining counts `1` and `0`.

- [ ] **Step 2: Run the test to verify RED**

Run from `source/app-graphics3d` using the Visual Studio developer environment:

```powershell
cl /nologo /EHsc /std:c++20 gpu_vulkan\tests\queue_host_call_diagnostics_test.cpp
```

Expected: compilation fails because `queue_host_call_diagnostics.h` does not exist.

- [ ] **Step 3: Add the minimal header-only implementation**

Implement a registry using `std::mutex`, `std::unordered_map<std::uintptr_t, std::weak_ptr<...>>`, and `std::shared_ptr`. Implement active count and serial using `std::atomic` fetch operations. Return a small entry record containing serial, active count, and `active_count > 1`.

- [ ] **Step 4: Register the header in the Visual Studio project and filters**

Add one `ClInclude` entry beside the other Vulkan queue headers and place it in the existing Header Files filter.

- [ ] **Step 5: Run the standalone test to verify GREEN**

Expected: compilation succeeds and the executable exits with code `0`.

---

### Task 2: Attach diagnostics to actual Vulkan queue identities

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/queue.h`
- Modify: `source/app-graphics3d/gpu_vulkan/queue.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/device.h`
- Modify: `source/app-graphics3d/gpu_vulkan/device.cpp`

**Interfaces:**
- Consumes: shared diagnostic state from Task 1.
- Produces: `queue_host_call_scope`, whose constructor enters the shared state and whose destructor leaves it.
- Produces: `gpu_vulkan::queue::m_pqueuehostcalldiagnosticstate` shared by wrappers with the same raw queue.

- [ ] **Step 1: Extend the failing test with scoped overlap behavior**

Add two shared owners for the same registry state and assert that entering through each owner detects overlap. This fails until the shared state is used as the queue-facing API expects.

- [ ] **Step 2: Verify the new assertion fails for the expected missing API**

Expected: compilation fails because the queue-facing scoped entry helper is not defined.

- [ ] **Step 3: Implement the scoped diagnostic guard**

The guard accepts a queue wrapper, operation name, command name, and annotation. On overlap it logs:

```text
gpu_vulkan queue host overlap: queue={} operation={} serial={} active_count={} task={} name={} annotation={}
```

It performs only atomic bookkeeping and logging; it does not acquire a Vulkan queue lock.

- [ ] **Step 4: Assign state by raw queue identity during device creation**

Add one device-owned registry. After each `vkGetDeviceQueue`, call `state_for((std::uintptr_t)queueHandle)` and assign the result to the wrapper. Equal graphics/transfer handles therefore receive the exact same state object.

- [ ] **Step 5: Re-run the standalone test**

Expected: exit code `0`.

---

### Task 3: Instrument active Vulkan queue host calls

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/command_buffer.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/context.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/swap_chain.cpp`

**Interfaces:**
- Consumes: `queue_host_call_scope` from Task 2.
- Produces: overlap evidence around all active wrapper-backed `vkQueueSubmit`, `vkQueueWaitIdle`, and `vkQueuePresentKHR` paths.

- [ ] **Step 1: Add a source-coverage test that enumerates active queue calls**

Create an assertion-based test that removes comments and verifies each active wrapper-backed queue call is immediately protected by a `queue_host_call_scope`. This test must fail on the current direct calls.

- [ ] **Step 2: Run the coverage test to verify RED**

Expected: executable exits nonzero because direct active calls remain.

- [ ] **Step 3: Add diagnostic guards around active calls**

Cover the command-buffer submit and post-submit wait, the CPU-sampling pre-copy wait, other active renderer/context waits, and swap-chain present. Pass command-buffer name and annotation where available; pass empty strings for wait/present sites without a command buffer.

- [ ] **Step 4: Run both focused tests to verify GREEN**

Expected: both executables exit with code `0`.

- [ ] **Step 5: Build the Vulkan solution target**

```powershell
MSBuild.exe solution-windows\SceneFoundry.sln /t:gpu_vulkan:ClCompile /p:Configuration=Debug /p:Platform=x64 /m /v:minimal /nologo
```

Expected: exit code `0`; existing unrelated compiler warnings may remain.

- [ ] **Step 6: Verify formatting and scope**

Run `git -C source/app-graphics3d diff --check`, confirm modified source files contain CRLF without bare LF, and inspect the diff to ensure no queue locking or rendering behavior change was introduced.

---

### Task 4: Runtime evidence collection

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: `gpu_vulkan queue host overlap` records.
- Produces: evidence selecting the next root-cause branch.

- [ ] **Step 1: Run Vulkan offscreen mode with validation enabled**

Load the same continuum scene and capture output through the first CPU sampling attempt.

- [ ] **Step 2: Interpret the result**

If an overlap message appears before `VK_ERROR_DEVICE_LOST`, host queue access is confirmed and the next design should serialize each raw queue. If no overlap message appears, reject that hypothesis and focus next on the sampling command itself, including staging-buffer readback and the preceding approximately 2.45-second layer duration as possible GPU-timeout evidence.
