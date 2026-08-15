# Graphics3D Frame Serial Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the authoritative GPU frame serial in the graphics3d statistics overlay without changing rotating frame-resource behavior.

**Architecture:** `::user::graphics3d::draw_gpu_statistics()` resolves its `::gpu::window_attachment` and uses `m_iFrameSerial2` for the first overlay line. Its existing local counter remains only as a null-attachment startup fallback. Because runtime verification showed rotating vkvg contexts freezing after mismatched save/restores, each draw2d_vkvg save token also records and restores its exact originating `VkvgContext`. `m_iCurrentFrame3` and all frame lifecycle methods remain untouched.

**Tech Stack:** C++17, ca2 bred GPU/window attachment, draw2d statistics overlay, MSBuild.

## Global Constraints

- Preserve unrelated changes in the shared dirty checkout.
- Preserve CRLF line endings in modified C++ source and test files.
- Do not modify frame restart, swap-chain, synchronization, or resource-index behavior.
- Do not stage or commit without explicit authorization.

---

### Task 1: Restore the authoritative frame serial in the overlay

**Files:**
- Modify: `source/app/bred/user/user/graphics3d.cpp:369-448`
- Create: `source/app/bred/user/user/tests/graphics3d_frame_serial_display_contract_test.cpp`

**Interfaces:**
- Consumes: `::gpu::window_attachment::get(::acme::user::interaction *)` and `window_attachment::m_iFrameSerial2`.
- Produces: The existing first statistics line formatted with the GPU frame serial, falling back to `++m_iFrameCounter` only when no attachment exists.

- [x] **Step 1: Write the failing regression contract**

Create a focused contract that identifies the `draw_gpu_statistics()` function and requires it to resolve a window attachment, select `m_iFrameSerial2`, retain a null-attachment fallback to `m_iFrameCounter`, and avoid `m_iCurrentFrame3`.

- [x] **Step 2: Run the contract to verify RED**

Run:

```powershell
$test = Join-Path $env:TEMP 'graphics3d_frame_serial_display_contract_test.exe'
g++ -std=c++17 source\app\bred\user\user\tests\graphics3d_frame_serial_display_contract_test.cpp -o $test
& $test
```

Expected: the executable fails because `draw_gpu_statistics()` currently formats `m_iFrameCounter` directly and does not read `m_iFrameSerial2`.

- [x] **Step 3: Implement the minimal serial selection**

In `draw_gpu_statistics()`, resolve the window attachment from `this`. Use its `m_iFrameSerial2` when available; otherwise increment and use `m_iFrameCounter`. Keep the existing text, FPS, and frame-time layout unchanged. Do not read `m_iCurrentFrame3`.

- [x] **Step 4: Run focused verification**

Rebuild and run the contract. Then build:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:bred /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: the contract and `bred` target pass. Record any pre-existing application-target dependency failure separately.

- [x] **Step 5: Verify the current runtime behavior**

Run continuum with the existing `on_screen` / `vkvg` / `vulkan` configuration. Confirm the overlay value advances using the GPU serial and does not cycle as `0, 1, 2`; also confirm the third composed layer remains present and Vulkan validation stays clean.

- [x] **Step 6: Review the scoped change**

Review only the two task files against their saved pre-change state. Address Critical or Important findings, rerun the focused contract and `bred` build, and leave all changes unstaged.

---

### Task 2: Preserve vkvg save/restore context identity

**Files:**
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.h`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.cpp`
- Create: `source/app-graphics3d/draw2d_vkvg/tests/saved_context_identity_contract_test.cpp`

- [x] **Step 1: Reproduce and trace the rotating display failure**

Confirm that `m_iFrameSerial2` is monotonic while the visible text rotates among initial layer values, then trace vkvg save and restore context handles.

- [x] **Step 2: Write and run a failing context-identity contract**

Require save tokens to store the exact `VkvgContext` and require restore to use that stored context instead of resolving the currently active target.

- [x] **Step 3: Implement context-aware save tokens**

Store saved contexts in stack order, return the stack index as the token, unwind recorded contexts in reverse order, and truncate the stack to the requested token.

- [x] **Step 4: Build focused targets and run continuum**

Build `draw2d_vkvg` and `bred`, run continuum under `on_screen` / `vkvg` / `vulkan`, capture multiple frames, verify the serial advances, confirm responsiveness and normal close, and scan output for vkvg restore, Vulkan validation, wrong-state, and draw-frame failures.

- [x] **Step 5: Final scoped review**

Review the overlay and saved-context changes, rerun contracts after any correction, and leave changes unstaged.
