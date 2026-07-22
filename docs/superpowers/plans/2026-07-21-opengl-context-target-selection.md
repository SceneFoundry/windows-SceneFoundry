# OpenGL Context Target Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenGL render a NanoVG memory-graphics layer directly into the GPU texture selected by its context so cached font previews contain transparent backgrounds and rendered text.

**Architecture:** `gpu_opengl::renderer::_on_begin_render()` will ask `gpu::context::current_target_texture()` for the color target. The context retains its existing render-target fallback for ordinary rendering, while NanoVG memory graphics can supply the destination `gpu::image` texture through its compositor override.

**Tech Stack:** C++17, OpenGL, NanoVG, SceneFoundry GPU/draw2d abstractions, MSBuild/Visual Studio 2026.

## Global Constraints

- Preserve existing behavior for contexts without a compositor-selected target.
- Do not add CPU image mapping or an additional GPU copy.
- Preserve CRLF line endings in modified and new C++ source files.
- Leave the implementation uncommitted for the user to commit and push.

---

### Task 1: Honor the Context-Selected OpenGL Render Target

**Files:**
- Create: `source/app/gpu_opengl/tests/context_target_selection_contract_test.cpp`
- Modify: `source/app/gpu_opengl/renderer.cpp:250-263`

**Interfaces:**
- Consumes: `gpu::context::current_target_texture(gpu::layer *) -> gpu::texture *`
- Produces: OpenGL render-target binding through the context-selected texture.

- [ ] **Step 1: Write the failing source contract**

Create `source/app/gpu_opengl/tests/context_target_selection_contract_test.cpp`:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char * pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string & source,
      const std::string & beginMarker,
      const std::string & endMarker)
   {

      auto begin = source.find(beginMarker);
      assert(begin != std::string::npos);

      auto end = source.find(endMarker, begin + beginMarker.size());
      assert(end != std::string::npos);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto source = read_file("gpu_opengl/renderer.cpp");
   const auto beginRender = section(
      source,
      "void renderer::_on_begin_render(::gpu::layer * pgpulayer)",
      "void renderer::on_begin_render(");

   assert(beginRender.find(
      "m_pgpucontext->current_target_texture(pgpulayer)") !=
      std::string::npos);
   assert(beginRender.find(
      "pgpurendertarget->current_texture(pgpulayer)") ==
      std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the source contract and verify RED**

Run from `source/app`:

```powershell
g++ gpu_opengl/tests/context_target_selection_contract_test.cpp -std=c++17 -o "$env:TEMP/context_target_selection_contract_test.exe"
& "$env:TEMP/context_target_selection_contract_test.exe"
```

Expected: assertion failure because `_on_begin_render()` still contains `pgpurendertarget->current_texture(pgpulayer)`.

- [ ] **Step 3: Select the target through the GPU context**

In `source/app/gpu_opengl/renderer.cpp`, replace:

```cpp
      auto pgpurendertarget = this->render_target();

      ::cast < texture > ptexture = pgpurendertarget->current_texture(pgpulayer);
```

with:

```cpp
      ::cast < texture > ptexture =
         m_pgpucontext->current_target_texture(pgpulayer);
```

Keep the existing depth-resource creation and `ptexture->bind_render_target()` calls unchanged.

- [ ] **Step 4: Run the source contract and verify GREEN**

Run the Step 2 commands again.

Expected: `context_target_selection_contract_test.exe` exits with code 0.

- [ ] **Step 5: Run related contracts**

Compile and run these contracts from their repository roots:

```powershell
g++ gpu_opengl/tests/gpu_image_pixel_transfer_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_pixel_transfer_contract_test.exe"
& "$env:TEMP/gpu_image_pixel_transfer_contract_test.exe"
```

From `source/app-graphics3d`:

```powershell
g++ draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp -std=c++17 -o "$env:TEMP/graphics_lease_integration_contract_test.exe"
& "$env:TEMP/graphics_lease_integration_contract_test.exe"
g++ draw2d_nanovg/tests/gpu_image_fast_path_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_fast_path_test.exe"
& "$env:TEMP/gpu_image_fast_path_test.exe"
g++ draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_lifecycle_test.exe"
& "$env:TEMP/gpu_image_lifecycle_test.exe"
g++ draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp -std=c++17 -o "$env:TEMP/memory_graphics_lifecycle_test.exe"
& "$env:TEMP/memory_graphics_lifecycle_test.exe"
```

Expected: every executable exits with code 0.

- [ ] **Step 6: Build the affected Debug x64 targets**

Run from the workspace root:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_opengl /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:draw2d_nanovg /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: all three commands exit with code 0.

- [ ] **Step 7: Hand off runtime validation**

Run `shared_app_graphics3d_continuum` with OpenGL and `draw2d_nanovg` in Visual Studio. Confirm that font previews show visible text over transparent backgrounds, scrolling remains responsive, no OpenGL 1282 exception occurs, and diagnostics continue to report `cpu_fallbacks=0`.

Do not commit; leave the specification, plan, test, and implementation available for the user's commit and push.
