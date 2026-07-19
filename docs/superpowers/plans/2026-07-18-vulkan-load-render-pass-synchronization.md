# Vulkan LOAD Render-Pass Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Vulkan attachment transitions and the render-pass external dependency expose the attachment reads performed by `VK_ATTACHMENT_LOAD_OP_LOAD`.

**Architecture:** A small Vulkan helper will define the color and depth access masks for clear-versus-load attachment use. The offscreen renderer and generic render-pass creation will consume that helper so their synchronization declarations cannot diverge while preserving the existing explicit transfer clears followed by `LOAD`.

**Tech Stack:** C++20, Vulkan 1.x, Visual Studio/MSBuild, standalone assertion test.

## Global Constraints

- Preserve explicit color/depth transfer clears and `VK_ATTACHMENT_LOAD_OP_LOAD` behavior.
- Keep the existing public GPU interfaces and `gpu_vulkan::queue` wrapper unchanged.
- Keep the main GPU context last in post-frame processing.
- Use CRLF line endings for modified C++ source, header, project, and test files.
- Do not make an intermediate commit; commit only after user-confirmed runtime success.

---

### Task 1: Define and Apply LOAD Attachment Access Masks

**Files:**
- Create: `source/app-graphics3d/gpu_vulkan/render_pass_load_sync.h`
- Create: `source/app-graphics3d/gpu_vulkan/tests/render_pass_load_sync_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/render_pass.cpp`

**Interfaces:**
- Produces: `gpu_vulkan::color_attachment_access(bool bLoadExisting)` and `gpu_vulkan::depth_attachment_access(bool bLoadExisting)`, each returning `VkAccessFlags`.
- Consumes: `bLoadExisting == true` for render passes that load an attachment and `false` for render passes that clear it.

- [ ] **Step 1: Write the failing behavior test**

Create a standalone assertion test that requires clear access to contain only the attachment write bit and load access to contain both the corresponding read and write bits:

```cpp
#include "../render_pass_load_sync.h"

#include <cassert>


int main()
{

   assert(gpu_vulkan::color_attachment_access(false) == VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT);
   assert(gpu_vulkan::color_attachment_access(true)
      == (VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT));
   assert(gpu_vulkan::depth_attachment_access(false) == VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT);
   assert(gpu_vulkan::depth_attachment_access(true)
      == (VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT));

   return 0;

}
```

- [ ] **Step 2: Compile the test and verify RED**

Compile with Visual Studio `cl`, adding the Vulkan SDK include directory and directing `.obj`/`.exe` output to `%TEMP%`.

Expected: compilation fails because `render_pass_load_sync.h` does not exist.

- [ ] **Step 3: Implement the minimal access-mask helper**

Create `render_pass_load_sync.h` with two `constexpr` functions. Each always includes its attachment write bit and conditionally includes its attachment read bit when `bLoadExisting` is true.

- [ ] **Step 4: Run the focused test and verify GREEN**

Expected: test compiles, exits `0`, and leaves no compiler artifacts in the workspace.

- [ ] **Step 5: Apply the helper to the active synchronization declarations**

In `renderer.cpp`, use `color_attachment_access(true)` and `depth_attachment_access(true)` for the transitions immediately after the explicit transfer clears and before `vkCmdBeginRenderPass`.

In `render_pass.cpp`, derive `bLoadExisting` as `!m_bLoadClearOp` and use the helper for the external dependency's color and, when enabled, depth access mask.

- [ ] **Step 6: Re-run focused and project verification**

Run the standalone test, `git diff --check`, verify CRLF in touched C++ files, and compile `gpu_vulkan:ClCompile` for Debug x64.

Expected: test exit code `0`, no whitespace errors, no bare LF in touched C++ files, and MSBuild exit code `0` (pre-existing warnings may remain).

- [ ] **Step 7: Runtime handoff**

Ask the user to rerun Vulkan offscreen rendering with synchronization validation. Success criteria are absence of the two `SYNC-HAZARD-READ-AFTER-WRITE` messages at `vkCmdBeginRenderPass`, no device loss during the previous failure window, and correct GDI+ presentation of the sampled scene.
