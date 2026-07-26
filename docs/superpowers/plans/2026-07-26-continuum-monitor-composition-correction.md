# Continuum Monitor Composition Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the complete live monitor composition and correct only the WIC-loaded ocean background's vertical orientation.

**Architecture:** Keep WIC decoding, OpenGL pixel transfer, HelloMultiverse upload, MSAA resolve, and quad publication unchanged. Give the offscreen composition pass an explicit full-target viewport/scissor and adapt only the background sampler's V coordinate in the composition shader.

**Tech Stack:** C++20, OpenGL 3.3 GLSL, SceneFoundry GPU abstractions, Visual Studio/MSBuild.

## Global Constraints

- Work directly on `main`, as explicitly authorized by the user.
- Preserve unrelated edits in `source/app/gpu_opengl/texture.cpp` and `source/app/gpu_opengl/texture.h`.
- Preserve existing line endings when practical.
- Use Windows CRLF line endings for modified C++ and GLSL source files.
- Do not change WIC decoding, generic GPU pixel transfer, HelloMultiverse overlay orientation, MSAA resolve, or resolved-texture publication.

---

### Task 1: Correct the Monitor Composition Extent and Background Orientation

**Files:**
- Modify: `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp`
- Modify: `source/app-graphics3d/continuum/main_scene.cpp`
- Modify: `source/app-graphics3d/continuum/opengl/overlay1.frag`
- Modify: `source/app-graphics3d/continuum/opengl/overlay1.frag.h`

**Interfaces:**
- Consumes: `::gpu::command_buffer::set_viewport(const ::i32_rectangle&)`, `::gpu::command_buffer::set_scissor(const ::i32_rectangle&)`, and `::gpu::texture::rectangle()`.
- Produces: A monitor composition pass covering the entire multisample target and a background-only `backgroundUv` V inversion.

- [ ] **Step 1: Extend the focused contract before production changes**

Add assertions that:

```cpp
const auto beginMonitorRender = beforeRender.find(
   "pgpucommandbuffer->begin_render(m_pgpushaderBlend, "
   "m_pgputextureMonitorMultisample);");
const auto monitorRectangle = beforeRender.find(
   "auto rectangleMonitor = "
   "m_pgputextureMonitorMultisample->rectangle();",
   beginMonitorRender);
const auto setViewport = beforeRender.find(
   "pgpucommandbuffer->set_viewport(rectangleMonitor);",
   monitorRectangle);
const auto setScissor = beforeRender.find(
   "pgpucommandbuffer->set_scissor(rectangleMonitor);",
   setViewport);
```

occur in that order before texture binding and drawing. Load both
`continuum/opengl/overlay1.frag` and
`continuum/opengl/overlay1.frag.h`; require the background-only
`backgroundUv` inversion and retain the existing overlay UV conversion.

- [ ] **Step 2: Run the focused contract and verify RED**

Run from `source/app-graphics3d`:

```powershell
g++ -std=c++20 continuum/tests/live_monitor_texture_contract_test.cpp -o "$env:TEMP\live_monitor_texture_contract_test.exe"
& "$env:TEMP\live_monitor_texture_contract_test.exe"
```

Expected: compilation succeeds and execution fails an assertion because the
explicit monitor viewport/scissor and background-only V inversion are absent.

- [ ] **Step 3: Implement the full-target render state**

Immediately after the monitor `begin_render` call in `main_scene.cpp`, add:

```cpp
auto rectangleMonitor =
   m_pgputextureMonitorMultisample->rectangle();

pgpucommandbuffer->set_viewport(rectangleMonitor);
pgpucommandbuffer->set_scissor(rectangleMonitor);
```

- [ ] **Step 4: Implement background-only vertical sampling correction**

In both shader representations, replace direct background sampling with:

```glsl
vec2 backgroundUv = vec2(
    viewportUv.x,
    1.0 - viewportUv.y);

vec4 backgroundColor =
    texture(backgroundTexture, backgroundUv);
```

Do not alter the overlay coordinate calculations.

- [ ] **Step 5: Run the focused contract and verify GREEN**

Run the command from Step 2 again.

Expected: exit code 0.

- [ ] **Step 6: Build the application target**

Run:

```powershell
msbuild solution-windows\SceneFoundry.sln /t:app_graphics3d_continuum /p:Configuration=Debug /p:Platform=x64 /m
```

Expected: build succeeds with zero errors.

- [ ] **Step 7: Review the final diff and preserve scope**

Confirm only the plan/spec, focused contract, `main_scene.cpp`, and the two
shader representations changed for this correction. Confirm the unrelated
`gpu_opengl` edits remain untouched.

