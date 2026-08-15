# Vulkan Shader Rebuild Target Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop on-screen Vulkan rendering from dereferencing the obsolete null shader target while retaining render-pass-compatible pipeline selection.

**Architecture:** Keep the destination `texture_site` passed through `command_buffer::begin_render()` as the authoritative Vulkan render target. Make the legacy Vulkan `need_rebuild()` hook return `false`; `_defer_set_current_pipeline()` continues to select or create pipelines in `m_mapRenderPassPipeline` using the explicit target's render pass.

**Tech Stack:** C++17, Vulkan, MSBuild, `shared_app_graphics3d_continuum` on Windows x64.

## Global Constraints

- Implement approved option 1 only: `gpu_vulkan::shader::need_rebuild()` returns `false`.
- Do not restore shader-side destination texture caching.
- Do not alter binding slots, framebuffer selection, or pipeline-cache behavior.
- Preserve CRLF line endings in modified C++ sources.
- Preserve all unrelated worktree changes.
- Do not commit implementation changes unless the user explicitly requests it.

---

### Task 1: Disable the obsolete Vulkan shader reconstruction check

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/shader.cpp:42`
- Verify: `source/app-graphics3d/gpu_vulkan/shader.h:115`
- Verify: `source/app-graphics3d/gpu_vulkan/command_buffer.cpp:760`

**Interfaces:**
- Consumes: `bool gpu_vulkan::shader::need_rebuild()` through `::nok(::pointer<::gpu::shader> &)`.
- Preserves: `shader::_defer_set_current_pipeline(::gpu::command_buffer *, ::gpu::texture_site *)` as the render-pass-compatible pipeline selector.
- Produces: `need_rebuild()` returning `false` without reading `m_ptextureTarget`.

- [ ] **Step 1: Establish the failing application-level regression**

Build the current targets from `C:\Users\camilo\SceneFoundry\main`:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_vulkan /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
```

Launch the currently configured on-screen Vulkan application:

```powershell
& time-windows\x64\Debug\shared_app_graphics3d_continuum.exe
```

Expected RED result: on a later `::nok(shader)` check, the process reaches `gpu_vulkan::shader::need_rebuild()` and fails when dereferencing the null `m_ptextureTarget`.

- [ ] **Step 2: Implement the minimal approved behavior**

Replace only the body of `gpu_vulkan::shader::need_rebuild()` with:

```cpp
   bool shader::need_rebuild()
   {

      return false;

   }
```

- [ ] **Step 3: Preserve Windows source line endings**

Run:

```powershell
unix2dos source\app-graphics3d\gpu_vulkan\shader.cpp
```

- [ ] **Step 4: Rebuild the affected targets**

Run:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_vulkan /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: both commands exit `0` and update the Debug x64 Vulkan DLL and application.

- [ ] **Step 5: Verify the on-screen Vulkan path**

Launch:

```powershell
& time-windows\x64\Debug\shared_app_graphics3d_continuum.exe
```

Expected GREEN result: the application passes repeated shader availability checks without a null-target exception, reaches the swap-chain presentation render, and displays the composed scene using `draw2d_vulkan` and `gpu_vulkan`.

- [ ] **Step 6: Review the scoped delta**

Run:

```powershell
git -C source/app-graphics3d diff --check -- gpu_vulkan/shader.cpp
git -C source/app-graphics3d diff -- gpu_vulkan/shader.cpp
```

Expected: no whitespace errors and the only behavioral change in `need_rebuild()` is `return false;`.
