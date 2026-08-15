# NanoVG Direct Layer Flush Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `draw2d_nanovg` flush queued OpenGL drawing into the active compositor layer texture before `merge_layers` samples it.

**Architecture:** Keep the direct-to-layer compositor path and correct only the NanoVG end-frame target selection. The active layer texture site resolved inside `graphics::on_end_layer()` becomes the authoritative flush target; the cached `m_pgputexturesiteTarget` remains exclusive to standalone memory-image graphics.

**Tech Stack:** C++17, NanoVG OpenGL backend, `gpu_opengl`, standalone source-contract tests, MSBuild Debug x64.

## Global Constraints

- Do not restore `layer_end_copy()`.
- Do not add an intermediate texture or framebuffer copy.
- Do not modify `merge_layers()`.
- Preserve CRLF line endings in modified C++ sources.
- Preserve existing unrelated worktree changes.

---

### Task 1: Flush NanoVG into the active layer texture

**Files:**
- Create: `source/app-graphics3d/draw2d_nanovg/tests/direct_layer_flush_target_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:9902`

**Interfaces:**
- Consumes: `::gpu::context::current_target_texture(::gpu::layer *) -> ::gpu::texture_site *`
- Consumes: `::gpu::texture_site::gpu_texture() -> ::gpu::texture *`
- Produces: `graphics::on_end_layer(::gpu::layer *)` binding the active layer's GPU texture immediately before `nvgEndFrame()`.

- [ ] **Step 1: Write the failing target-selection contract**

Create a standalone contract test that reads `graphics.cpp`, isolates the `graphics::on_end_layer()` function, and asserts both null checks and the local target lookup:

```cpp
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read(const std::filesystem::path & path)
   {

      std::ifstream stream(path);
      assert(stream);
      return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};

   }


} // namespace


int main()
{

   const auto draw2dNanovg = std::filesystem::path(__FILE__).parent_path().parent_path();
   const auto source = read(draw2dNanovg / "graphics.cpp");
   const auto begin = source.find("void graphics::on_end_layer(::gpu::layer* pgpulayer)");
   const auto end = source.find("void graphics::begin_draw()", begin);

   assert(begin != std::string::npos);
   assert(end != std::string::npos);

   const auto onEndLayer = source.substr(begin, end - begin);

   assert(onEndLayer.find(
      "if (!pgputexturesiteTarget || !pgputexturesiteTarget->gpu_texture())") !=
      std::string::npos);
   assert(onEndLayer.find(
      "auto pgputextureTarget = pgputexturesiteTarget->gpu_texture();") !=
      std::string::npos);
   assert(onEndLayer.find(
      "auto pgputextureTarget = m_pgputexturesiteTarget->gpu_texture();") ==
      std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Compile and run the contract to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
g++ -std=c++17 source\app-graphics3d\draw2d_nanovg\tests\direct_layer_flush_target_contract_test.cpp -o $env:TEMP\direct_layer_flush_target_contract_test.exe
& $env:TEMP\direct_layer_flush_target_contract_test.exe
```

Expected: the executable aborts because the current function dereferences `m_pgputexturesiteTarget` instead of the locally resolved active layer texture site.

- [ ] **Step 3: Implement the minimal active-layer correction**

In `graphics::on_end_layer()`, replace the existing site-only guard and cached-member lookup with:

```cpp
      if (!pgputexturesiteTarget || !pgputexturesiteTarget->gpu_texture())
      {

         throw ::exception(
            error_wrong_state,
            "NanoVG has no current GPU target at the end-frame flush boundary.");

      }

      auto pgputextureTarget = pgputexturesiteTarget->gpu_texture();
```

Do not alter `prepare_nanovg_render_target()`, `nvgEndFrame()`, `glFlush()`, or compositor code.

- [ ] **Step 4: Preserve Windows source line endings**

Run:

```powershell
unix2dos source\app-graphics3d\draw2d_nanovg\graphics.cpp
unix2dos source\app-graphics3d\draw2d_nanovg\tests\direct_layer_flush_target_contract_test.cpp
```

- [ ] **Step 5: Run the contract to verify GREEN**

Run:

```powershell
g++ -std=c++17 source\app-graphics3d\draw2d_nanovg\tests\direct_layer_flush_target_contract_test.cpp -o $env:TEMP\direct_layer_flush_target_contract_test.exe
& $env:TEMP\direct_layer_flush_target_contract_test.exe
```

Expected: exit code `0` with no assertion failures.

- [ ] **Step 6: Build the affected OpenGL modules**

Run:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:draw2d_nanovg /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_opengl /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: both targets exit `0` and produce `draw2d_nanovg.dll` and `gpu_opengl.dll` in `time-windows\x64\Debug`.

- [ ] **Step 7: Verify the original offscreen composition symptom**

Launch `time-windows\x64\Debug\shared_app_graphics3d_continuum.exe` in its `draw2d_nanovg gpu_opengl` configuration. Confirm the window title identifies both modules. At `merge_layers`, confirm each active 2D layer texture contains the NanoVG output and the final image composites those layers with the 3D scene.

- [ ] **Step 8: Review only the scoped changes**

Run:

```powershell
git -C source/app-graphics3d diff --check -- draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/direct_layer_flush_target_contract_test.cpp
git -C source/app-graphics3d diff -- draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/direct_layer_flush_target_contract_test.cpp
```

Expected: no whitespace errors; the production delta is limited to validation plus replacing the cached target lookup with the active layer target lookup.

- [ ] **Step 9: Commit the implementation only if requested**

Do not stage or commit the implementation unless the user explicitly asks. The workspace contains unrelated changes that must remain untouched.
