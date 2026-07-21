# draw2d_nanovg Memory Graphics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a recreatable, GPU-resident NanoVG memory graphics context that draws offscreen without requiring an `image::image` or presenting to a swap chain.

**Architecture:** The public method normalizes an empty size to `1920 x 1080` and delegates to the generic graphics lifecycle. A NanoVG `_create_memory_graphics` override destroys the previous NanoVG context while its OpenGL context is current, creates an `e_output_gpu_buffer` draw2d context, and constructs a fresh NanoVG GL3 context against the new offscreen target.

**Tech Stack:** C++20, SceneFoundry draw2d/gpu framework, OpenGL, NanoVG GL3, MSVC/Visual Studio 2026, Debug x64.

## Global Constraints

- Preserve the user's current edits in `draw2d_nanovg/graphics.cpp` and `graphics.h`; do not restore the recursive `opengl_create_offscreen_buffer` implementation.
- Preserve Windows CRLF line endings in modified C++ files.
- An empty requested size allocates exactly `1920 x 1080`.
- The memory graphics target uses `gpu::e_output_gpu_buffer` and does not create or present a swap chain.
- Do not allocate or require an `image::image`.
- Repeated creation deletes the old `NVGcontext` while its original OpenGL context is current, then creates a new GPU target and `NVGcontext`.
- Do not commit generated `.exe` or `.obj` test artifacts.

---

## File Structure

- Create `source/app-graphics3d/draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp`: dependency-free source-level regression probe for the public fallback, backend lifecycle, recreation ordering, and bitmap-selection integration.
- Modify `source/app-graphics3d/draw2d_nanovg/graphics.h`: declare the framework `_create_memory_graphics` override while leaving the recursive helper declarations disabled.
- Modify `source/app-graphics3d/draw2d_nanovg/graphics.cpp`: normalize the public size, implement the offscreen NanoVG backend hook, and route bitmap selection through the new memory-graphics lifecycle.

### Task 1: Offscreen NanoVG memory-graphics lifecycle

**Files:**
- Create: `source/app-graphics3d/draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h:138-149`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:220-248`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:719-748`

**Interfaces:**
- Consumes: `gpu::device::create_draw2d_context(gpu::enum_output, const i32_size&)`, `gpu::compositor::set_gpu_context(gpu::context*)`, `gpu::context_lock`, `gpu::context::get_gpu_renderer()`, `nvgCreateGL3`, and `nvgDeleteGL3`.
- Produces: `draw2d_nanovg::graphics::_create_memory_graphics(const ::i32_size&)` and a public `create_memory_graphics` that always delegates with a non-empty size.

- [x] **Step 1: Write the failing lifecycle regression test**

Create `draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp`:

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

      const auto begin = source.find(beginMarker);
      const auto end = source.find(endMarker, begin);

      assert(begin != std::string::npos);
      assert(end != std::string::npos);
      assert(begin < end);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto header = read_file("draw2d_nanovg/graphics.h");
   const auto source = read_file("draw2d_nanovg/graphics.cpp");

   assert(header.find(
      "void _create_memory_graphics(const ::i32_size & size) override;") !=
      std::string::npos);

   const auto publicCreation = section(
      source,
      "void graphics::create_memory_graphics(",
      "void graphics::_create_memory_graphics(");

   const auto fallback = publicCreation.find("sizeMemory = { 1920, 1080 };");
   const auto delegation = publicCreation.find(
      "::gpu::graphics::create_memory_graphics(sizeMemory);");

   assert(fallback != std::string::npos);
   assert(delegation != std::string::npos);
   assert(fallback < delegation);
   assert(publicCreation.find("opengl_create_offscreen_buffer") ==
      std::string::npos);

   const auto backendCreation = section(
      source,
      "void graphics::_create_memory_graphics(",
      "void graphics::create_window_graphics(");

   const auto deleteOldNanoVg = backendCreation.find("nvgDeleteGL3(pdcOld);");
   const auto createGpuContext = backendCreation.find("create_draw2d_context(");
   const auto gpuBufferOutput = backendCreation.find(
      "::gpu::e_output_gpu_buffer", createGpuContext);
   const auto assignContext = backendCreation.find(
      "set_gpu_context(pgpucontextNew);", createGpuContext);
   const auto assignCompositor = backendCreation.find(
      "pgpucontextNew->m_pgpucompositor = this;", assignContext);
   const auto ensureRenderer = backendCreation.find(
      "pgpucontextNew->get_gpu_renderer();", assignCompositor);
   const auto createNanoVg = backendCreation.find(
      "nvgCreateGL3(NVG_ANTIALIAS | NVG_STENCIL_STROKES | NVG_DEBUG)",
      ensureRenderer);

   assert(deleteOldNanoVg != std::string::npos);
   assert(createGpuContext != std::string::npos);
   assert(gpuBufferOutput != std::string::npos);
   assert(assignContext != std::string::npos);
   assert(assignCompositor != std::string::npos);
   assert(ensureRenderer != std::string::npos);
   assert(createNanoVg != std::string::npos);
   assert(deleteOldNanoVg < createGpuContext);
   assert(createGpuContext < gpuBufferOutput);
   assert(gpuBufferOutput < assignContext);
   assert(assignContext < assignCompositor);
   assert(assignCompositor < ensureRenderer);
   assert(ensureRenderer < createNanoVg);
   assert(backendCreation.find("m_sizeScaleOutput = { 1.0, -1.0 };") !=
      std::string::npos);
   assert(backendCreation.find(
      "m_pointTranslateOutput = { 0.0, (double)size.cy };") !=
      std::string::npos);
   assert(backendCreation.find("opengl_create_offscreen_buffer") ==
      std::string::npos);

   const auto bitmapSelection = section(
      source,
      "::draw2d::bitmap* graphics::SelectObject(::draw2d::bitmap* pbitmap)",
      "::draw2d::object* graphics::SelectObject(::draw2d::object* pObject)");

   assert(bitmapSelection.find("create_memory_graphics(pbitmap->get_size());") !=
      std::string::npos);
   assert(bitmapSelection.find("opengl_create_offscreen_buffer") ==
      std::string::npos);
   assert(bitmapSelection.find("opengl_delete_offscreen_buffer") ==
      std::string::npos);

   return 0;

}
```

- [x] **Step 2: Compile and run the test to verify RED**

From `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d` in a Visual Studio x64 developer environment:

```powershell
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\memory_graphics_lifecycle_test.cpp /Fe:memory_graphics_lifecycle_test.exe
.\memory_graphics_lifecycle_test.exe
```

Expected: compilation succeeds, then the executable fails its first assertion because `graphics.h` does not yet declare `_create_memory_graphics`.

- [x] **Step 3: Declare the NanoVG backend hook**

In `draw2d_nanovg/graphics.h`, place the protected framework hook directly after the public method:

```cpp
      void create_memory_graphics(const ::i32_size & size = {}) override;
      void _create_memory_graphics(const ::i32_size & size) override;
```

Keep both `opengl_create_offscreen_buffer` and `opengl_delete_offscreen_buffer` declarations commented out.

- [x] **Step 4: Implement public normalization and backend creation**

Replace the current empty public implementation in `draw2d_nanovg/graphics.cpp` and insert the backend hook before `create_window_graphics`:

```cpp
   void graphics::create_memory_graphics(const ::i32_size& size)
   {

      ::i32_size sizeMemory(size);

      if (sizeMemory.is_empty())
      {

         sizeMemory = { 1920, 1080 };

      }

      ::gpu::graphics::create_memory_graphics(sizeMemory);

   }


   void graphics::_create_memory_graphics(const ::i32_size& size)
   {

      auto puserinteraction = m_puserinteractionDraw2dGraphics;

      if (!puserinteraction)
      {

         puserinteraction = dynamic_cast < ::user::interaction * >(
            application()->m_pacmeuserinteractionMain.m_p);

      }

      if (!puserinteraction)
      {

         throw ::exception(
            error_wrong_state,
            "No main interaction is available for NanoVG memory graphics.");

      }

      auto pwindow = puserinteraction->window();

      if (!pwindow)
      {

         throw ::exception(
            error_wrong_state,
            "No window is available to acquire the OpenGL GPU device.");

      }

      m_puserinteractionDraw2dGraphics = puserinteraction;

      if (m_pdc)
      {

         auto pgpucontextOld = gpu_context();

         if (!pgpucontextOld)
         {

            throw ::exception(
               error_wrong_state,
               "NanoVG context has no owning OpenGL GPU context.");

         }

         ::gpu::context_lock contextlockOld(pgpucontextOld);

         auto pdcOld = m_pdc;
         m_pdc = nullptr;
         nvgDeleteGL3(pdcOld);

      }

      auto pgpuapproach = application()->get_gpu_approach();
      auto pgpudevice = pgpuapproach->get_gpu_device(pwindow);

      if (!pgpudevice)
      {

         throw ::exception(
            error_wrong_state,
            "Failed to acquire the OpenGL GPU device for NanoVG memory graphics.");

      }

      auto pgpucontextNew = pgpudevice->create_draw2d_context(
         ::gpu::e_output_gpu_buffer,
         size);

      if (!pgpucontextNew)
      {

         throw ::exception(
            error_wrong_state,
            "Failed to create the NanoVG offscreen GPU context.");

      }

      set_gpu_context(pgpucontextNew);
      pgpucontextNew->m_pgpucompositor = this;

      m_sizeScaleOutput = { 1.0, -1.0 };
      m_pointTranslateOutput = { 0.0, (double)size.cy };
      m_size = size;
      m_sizeWindow = size;

      {

         ::gpu::context_lock contextlockNew(pgpucontextNew);

         pgpucontextNew->get_gpu_renderer();
         ::opengl::resize(size, false);

         m_pdc = nvgCreateGL3(NVG_ANTIALIAS | NVG_STENCIL_STROKES | NVG_DEBUG);

         if (!m_pdc)
         {

            throw ::exception(
               error_failed,
               "nvgCreateGL3 failed for NanoVG memory graphics.");

         }

      }

   }
```

The generic `draw2d::graphics::create_memory_graphics` implementation sets the ready flag only after this virtual hook returns successfully.

- [x] **Step 5: Route bitmap selection through the new lifecycle**

In `graphics::SelectObject(::draw2d::bitmap*)`, replace the disabled helper calls and redundant resize block:

```cpp
      create_memory_graphics(pbitmap->get_size());

      m_pbitmap = pbitmap;

      return m_pbitmap;
```

This preserves bitmap selection semantics without making the offscreen target depend on the bitmap's pixel storage.

- [x] **Step 6: Run the lifecycle test to verify GREEN**

```powershell
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\memory_graphics_lifecycle_test.cpp /Fe:memory_graphics_lifecycle_test.exe
.\memory_graphics_lifecycle_test.exe
```

Expected: compilation succeeds and the executable exits with code `0`.

- [x] **Step 7: Build the NanoVG backend**

From `C:\Users\camilo\SceneFoundry\main`:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
   'solution-windows\SceneFoundry.sln' `
   /t:draw2d_nanovg `
   /p:Configuration=Debug `
   /p:Platform=x64 `
   /m:1 `
   /nodeReuse:false `
   /nologo `
   /v:minimal
```

Expected: MSBuild exits with code `0` and produces `time-windows\x64\Debug\draw2d_nanovg.dll`.

- [ ] **Step 8: Runtime verification checkpoint**

Exercise a NanoVG graphics object with `create_memory_graphics({})`, draw a transparent clear plus a rectangle, path, ellipse, and text, and finish the frame/layer. Confirm:

- the target dimensions are `1920 x 1080`;
- no draw is presented directly to a window;
- the GPU target contains the rendered primitives when inspected or sampled;
- a second `create_memory_graphics({ 640, 360 })` call succeeds;
- subsequent drawing targets the new `640 x 360` texture;
- no OpenGL or NanoVG validation/debug error appears.

- [ ] **Step 9: Commit after runtime confirmation**

```powershell
git -C source/app-graphics3d add -- `
   draw2d_nanovg/graphics.cpp `
   draw2d_nanovg/graphics.h `
   draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "Implement NanoVG offscreen memory graphics"
```

Expected: only the two NanoVG source files and lifecycle regression test are committed; generated test executables/objects remain untracked.
