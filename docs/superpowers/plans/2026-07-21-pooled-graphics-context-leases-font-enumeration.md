# Pooled Graphics/Context Leases and Font Enumeration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add warm, exclusive graphics/context leases and migrate font measurement plus preview rendering so font enumeration no longer creates GPU contexts and threads proportional to CPU affinity or image count.

**Architecture:** `gpu::device` owns reusable draw2d contexts exposed through move-only `gpu::context_lease`. `draw2d::draw2d` owns reusable memory graphics exposed through move-only `draw2d::graphics_lease`; a warm GPU graphics retains its context lease while idle. Font enumeration uses one measurement lease, and preview images acquire short destination leases without retaining graphics or contexts.

**Tech Stack:** C++20, SceneFoundry `aura`/`bred`, `std::atomic`, existing ca2 pointer/synchronization/task primitives, NanoVG GL3/OpenGL, MSVC/Visual Studio, source-contract tests.

## Global Constraints

- Preserve current user changes in the dirty root, `source/app`, and `source/app-graphics3d` repositories; stage only files named by the active task.
- Preserve existing line endings where practical and use Windows CRLF for modified/new C++ files.
- Pool only memory/offscreen graphics; do not pool window or swapchain graphics.
- Leases are move-only, exclusive, may be stored persistently, and have non-throwing destructors plus explicit `close()`.
- Returned damaged resources are destroyed rather than reused.
- Idle graphics retain their `gpu::context_lease`; idle/LRU eviction is out of scope.
- An image permits only one active destination graphics lease.
- Font measurement uses exactly one graphics lease across both extent phases; do not retain GPU parallelism in this first slice.
- Existing runtime GPU diagnostics control all new reports and remain disabled by default.
- Disabled diagnostic paths do no clock reads, formatting, allocation, or counter updates beyond one relaxed enabled-flag load.
- Do not change the existing GPU-only NanoVG source-image fast path or introduce CPU image mapping.
- This plan deliberately leaves legacy `g()`/`get_graphics()` available outside the migrated vertical slice. The approved repository-wide `g()` to `g2()` compile break is a separate follow-up because it spans hundreds of calls and multiple unbuilt platforms.

---

## File Structure

### `source/app` (`app` nested repository)

- Create `bred/gpu/context_lease.h/.cpp`: move-only context checkout and return.
- Modify `bred/gpu/device.h/.cpp`: device-owned idle context pool, acquisition/return/shutdown, diagnostics.
- Modify `bred/bred.vcxproj` and `bred/bred.vcxproj.filters`: compile/include new lease files.
- Create `bred/gpu/tests/context_lease_pool_contract_test.cpp`: context lease/pool source contract.
- Create `aura/graphics/draw2d/graphics_lease.h/.cpp`: move-only graphics checkout and return.
- Modify `aura/graphics/draw2d/draw2d.h/.cpp`: draw2d-owned idle memory-graphics pool and diagnostics.
- Modify `aura/graphics/draw2d/graphics.h/.cpp`: backend-neutral lease bind/release hooks.
- Modify `aura/graphics/image/image.h/.cpp`: image acquisition API and destination-lease exclusivity.
- Modify `aura/aura.vcxproj` and `aura/aura.vcxproj.filters`: compile/include new lease files.
- Create `aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp`: graphics lease/pool contract.
- Modify `bred/gpu/graphics.h/.cpp`: warm `gpu::context_lease` ownership and context resizing.
- Modify `aura/graphics/write_text/font_list.h/.cpp`: single measurement lease and enumeration timings.
- Modify `aura/graphics/write_text/text_box.cpp`: short preview-image graphics lease.
- Create `aura/graphics/write_text/tests/font_enumeration_graphics_lease_contract_test.cpp`: font vertical-slice contract.

### `source/app-graphics3d` (`app-graphics3d` nested repository)

- Modify `draw2d_nanovg/graphics.h/.cpp`: acquire pooled context, bind/unbind leased image targets, retain warm NanoVG state.
- Modify `draw2d_nanovg/image.h/.cpp`: remove persistent graphics creation from the migrated acquisition path while retaining legacy `_get_graphics()` temporarily.
- Create `draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp`: NanoVG lease integration contract.

---

### Task 1: Device-Owned GPU Context Leases

**Files:**
- Create: `source/app/bred/gpu/context_lease.h`
- Create: `source/app/bred/gpu/context_lease.cpp`
- Modify: `source/app/bred/gpu/device.h`
- Modify: `source/app/bred/gpu/device.cpp`
- Modify: `source/app/bred/bred.vcxproj`
- Modify: `source/app/bred/bred.vcxproj.filters`
- Create: `source/app/bred/gpu/tests/context_lease_pool_contract_test.cpp`

**Interfaces:**
- Consumes: `gpu::device::create_draw2d_context(enum_output, size)` and `gpu::context::on_resize(size)`.
- Produces: `gpu::context_lease`, `device::acquire_draw2d_context(...)`, `device::return_draw2d_context(...)`, and `device::shutdown_draw2d_context_pool()`.

- [ ] **Step 1: Write the failing context-pool contract test**

Create a standalone source test that reads `context_lease.h/.cpp` and `device.h/.cpp`. Its `main()` must assert:

```cpp
int main()
{
   const auto leaseHeader = read_file("bred/gpu/context_lease.h");
   const auto leaseSource = read_file("bred/gpu/context_lease.cpp");
   const auto deviceHeader = read_file("bred/gpu/device.h");
   const auto deviceSource = read_file("bred/gpu/device.cpp");

   assert(leaseHeader.find("context_lease(const context_lease &) = delete;") != std::string::npos);
   assert(leaseHeader.find("context_lease & operator=(const context_lease &) = delete;") != std::string::npos);
   assert(leaseHeader.find("context_lease(context_lease &&") != std::string::npos);
   assert(leaseHeader.find("void close();") != std::string::npos);
   assert(leaseHeader.find("void mark_damaged();") != std::string::npos);
   assert(leaseSource.find("return_draw2d_context") != std::string::npos);
   assert(deviceHeader.find("acquire_draw2d_context") != std::string::npos);
   assert(deviceHeader.find("m_contextaDraw2dIdle") != std::string::npos);
   assert(deviceSource.find("[gpu.context_pool]") != std::string::npos);
   assert(deviceSource.find("on_resize(size)") != std::string::npos);
   return 0;
}
```

Use the established `read_file()` helper from the existing source-contract tests.

- [ ] **Step 2: Run RED**

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cd /d C:\Users\camilo\SceneFoundry\main\source\app && cl.exe /nologo /std:c++20 /EHsc bred\gpu\tests\context_lease_pool_contract_test.cpp /Fo:`"$env:TEMP\context_lease_pool_contract_test.obj`" /Fe:`"$env:TEMP\context_lease_pool_contract_test.exe`" && `"$env:TEMP\context_lease_pool_contract_test.exe`""
```

Expected: compilation succeeds and the executable aborts because the lease files/interfaces are absent.

- [ ] **Step 3: Add the move-only `gpu::context_lease` interface**

Create `context_lease.h` with this public surface:

```cpp
namespace gpu
{
   class CLASS_DECL_BRED context_lease
   {
   public:
      ::pointer<::gpu::device> m_pdevice;
      ::pointer<::gpu::context> m_pcontext;
      bool m_bDamaged = false;

      context_lease();
      context_lease(::gpu::device * pdevice, ::gpu::context * pcontext);
      context_lease(const context_lease &) = delete;
      context_lease & operator=(const context_lease &) = delete;
      context_lease(context_lease && lease) noexcept;
      context_lease & operator=(context_lease && lease) noexcept;
      ~context_lease() noexcept;

      explicit operator bool() const;
      ::gpu::context * get() const;
      ::gpu::context * operator->() const;
      void mark_damaged();
      void close();
      void close_noexcept() noexcept;
   };
}
```

Implement move construction/assignment by transferring both pointers and clearing the source. `close()` must detach its local pointers before calling the device return function so repeated close is harmless. `close_noexcept()` wraps `close()` in `try/catch`, logs the error, and never rethrows. The destructor calls `close_noexcept()`.

- [ ] **Step 4: Add the device context pool**

Add these members and methods to `gpu::device`:

```cpp
::pointer_array<::gpu::context> m_contextaDraw2dIdle;
::std::atomic_bool m_bDraw2dContextPoolShuttingDown{false};
::std::atomic<::u64> m_uDraw2dContextPoolAcquisitions{0};
::std::atomic<::u64> m_uDraw2dContextPoolReuses{0};
::std::atomic<::u64> m_uDraw2dContextPoolCreations{0};
::std::atomic<::u64> m_uDraw2dContextPoolActive{0};
::std::atomic<::u64> m_uDraw2dContextPoolHighWater{0};

virtual ::gpu::context_lease acquire_draw2d_context(
   const ::gpu::enum_output & eoutput,
   const ::i32_size & size);
virtual void return_draw2d_context(
   ::pointer<::gpu::context> pcontext,
   bool bDamaged);
virtual void shutdown_draw2d_context_pool();
virtual void report_draw2d_context_pool_diagnostics_if_due();
```

`acquire_draw2d_context()` must:

1. reject shutdown and empty sizes;
2. remove one idle context with matching `m_eoutput` and `e_type_draw2d` while holding `device::synchronization()`;
3. otherwise call the existing `create_draw2d_context()` outside the pool lock;
4. synchronously call `pcontext->on_resize(size)` on a reused context thread;
5. clear `m_pgpucompositor` before returning; and
6. increment active/high-water counters only when diagnostics are enabled.

`return_draw2d_context()` synchronously clears the compositor and bound shader state. It adds a healthy context to the idle array, but destroys/releases a damaged context or any context returned during shutdown. Decrement active count exactly once.

Call `shutdown_draw2d_context_pool()` at the beginning of device destruction, before releasing the device's main/work contexts. Shutdown atomically rejects new acquisitions, transfers the idle array to a local array under the device lock, and destroys that local array after unlocking.

- [ ] **Step 5: Register files, run GREEN, and build `bred`**

Add `context_lease.cpp` as `ClCompile` and `context_lease.h` as `ClInclude` in the project and filters files. Run the contract command from Step 2, then:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:bred /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: test and build exit `0`.

- [ ] **Step 6: Commit Task 1**

Stage only the seven Task 1 files in `source/app`, run `git diff --cached --check`, and commit:

```text
Add pooled GPU context leases
```

### Task 2: Draw2d Graphics Leases and Memory-Graphics Pool

**Files:**
- Create: `source/app/aura/graphics/draw2d/graphics_lease.h`
- Create: `source/app/aura/graphics/draw2d/graphics_lease.cpp`
- Modify: `source/app/aura/graphics/draw2d/draw2d.h`
- Modify: `source/app/aura/graphics/draw2d/draw2d.cpp`
- Modify: `source/app/aura/graphics/draw2d/graphics.h`
- Modify: `source/app/aura/graphics/draw2d/graphics.cpp`
- Modify: `source/app/aura/aura.vcxproj`
- Modify: `source/app/aura/aura.vcxproj.filters`
- Create: `source/app/aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp`

**Interfaces:**
- Consumes: existing `draw2d::draw2d::create_graphics(host)` and `graphics::create_memory_graphics(size)`.
- Produces: `draw2d::graphics_lease`, measurement acquisition, image-target acquisition, and backend lease hooks.

- [ ] **Step 1: Write the failing graphics-pool contract test**

Assert the following source contract:

```cpp
assert(leaseHeader.find("graphics_lease(const graphics_lease &) = delete;") != std::string::npos);
assert(leaseHeader.find("graphics_lease(graphics_lease &&") != std::string::npos);
assert(leaseHeader.find("void close();") != std::string::npos);
assert(draw2dHeader.find("acquire_memory_graphics") != std::string::npos);
assert(draw2dHeader.find("acquire_image_graphics") != std::string::npos);
assert(draw2dHeader.find("m_graphicsaMemoryPoolIdle") != std::string::npos);
assert(graphicsHeader.find("on_acquire_memory_graphics") != std::string::npos);
assert(graphicsHeader.find("on_release_memory_graphics") != std::string::npos);
assert(draw2dSource.find("[draw2d.graphics_pool]") != std::string::npos);
```

- [ ] **Step 2: Run RED**

Compile/run the test from `source/app` with the same MSVC command shape as Task 1. Expected: abort because the APIs are absent.

- [ ] **Step 3: Implement `draw2d::graphics_lease`**

Use this public interface:

```cpp
namespace draw2d
{
   class CLASS_DECL_AURA graphics_lease
   {
   public:
      ::pointer<::draw2d::draw2d> m_pdraw2d;
      ::draw2d::graphics_pointer m_pgraphics;
      ::image::image_pointer m_pimage;
      bool m_bDamaged = false;

      graphics_lease();
      graphics_lease(
         ::draw2d::draw2d * pdraw2d,
         ::draw2d::graphics * pgraphics,
         ::image::image * pimage);
      graphics_lease(const graphics_lease &) = delete;
      graphics_lease & operator=(const graphics_lease &) = delete;
      graphics_lease(graphics_lease && lease) noexcept;
      graphics_lease & operator=(graphics_lease && lease) noexcept;
      ~graphics_lease() noexcept;

      explicit operator bool() const;
      ::draw2d::graphics * get() const;
      ::draw2d::graphics * operator->() const;
      void mark_damaged();
      void close();
      void close_noexcept() noexcept;
   };
}
```

As with `context_lease`, detach local state before return, make repeated close harmless, and prevent destructor exceptions.

- [ ] **Step 4: Add graphics lease lifecycle hooks**

Add to `draw2d::graphics`:

```cpp
virtual bool is_memory_graphics_pool_compatible(::draw2d::host * pdraw2dhost) const;
virtual void on_acquire_memory_graphics(
   ::image::image * pimage,
   const ::i32_size & size);
virtual void on_release_memory_graphics();
```

The base acquisition hook rejects an already bound `m_pimage`, stores the optional image, calls `defer_set_size(size)`, resets clip/origin/alpha mode to their normal defaults, and clears transient selected objects that cannot cross borrowers. The release hook calls `sync_flush()`, resets clip and transient state, and sets `m_pimage` to `nullptr`.

- [ ] **Step 5: Add the central draw2d pool**

Add idle storage, shutdown state, diagnostics counters, and these methods to `draw2d::draw2d`:

```cpp
virtual ::draw2d::graphics_lease acquire_memory_graphics(
   ::draw2d::host * pdraw2dhost,
   const ::i32_size & size);
virtual ::draw2d::graphics_lease acquire_image_graphics(
   ::image::image * pimage,
   ::draw2d::host * pdraw2dhost);
virtual void return_memory_graphics(
   ::draw2d::graphics_pointer pgraphics,
   ::image::image_pointer pimage,
   bool bDamaged);
virtual void shutdown_memory_graphics_pool();
virtual void report_memory_graphics_pool_diagnostics_if_due();
```

Use `m_graphicsaMemoryPoolIdle` under `draw2d::draw2d::synchronization()`. Reuse the first entry whose virtual compatibility check succeeds. Create outside the pool lock using `create_graphics(pdraw2dhost)` and `create_memory_graphics(size)`. Call the acquisition hook before constructing the lease. On return, call the release hook first; damaged/shutdown entries are destroyed instead of reinserted.

The image-target overload uses `pimage->size()` and leaves image exclusivity to Task 3.

Call `shutdown_memory_graphics_pool()` at the beginning of `draw2d::draw2d::destroy()`, before clearing backend object lists. Shutdown rejects new acquisitions, detaches the idle array under the draw2d lock, and destroys those graphics after unlocking.

- [ ] **Step 6: Register files, run GREEN, and build `aura`**

Register the new source/header in the Aura project files, run the contract, and build target `aura` Debug/x64 with `/m:1 /nr:false`. Expected: all exit `0`.

- [ ] **Step 7: Commit Task 2**

Commit only Task 2 files in `source/app` with:

```text
Add pooled draw2d graphics leases
```

### Task 3: Image Acquisition and Exclusive Destination Binding

**Files:**
- Modify: `source/app/aura/graphics/image/image.h`
- Modify: `source/app/aura/graphics/image/image.cpp`
- Modify: `source/app/bred/gpu/image.cpp`
- Extend: `source/app/aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp`

**Interfaces:**
- Consumes: `draw2d::draw2d::acquire_image_graphics()` from Task 2.
- Produces: `image::acquire_graphics(host)`, active-lease CAS, and map/destroy guards.

- [ ] **Step 1: Extend the contract test and run RED**

Add assertions for:

```cpp
assert(imageHeader.find("::draw2d::graphics_lease acquire_graphics") != std::string::npos);
assert(imageHeader.find("m_bDestinationGraphicsLeaseActive") != std::string::npos);
assert(imageSource.find("compare_exchange_strong") != std::string::npos);
assert(imageSource.find("end_destination_graphics_lease") != std::string::npos);
assert(gpuImageMap.find("has_active_destination_graphics_lease()") != std::string::npos);
```

Run the test and expect failure before implementation.

- [ ] **Step 2: Add image lease state and acquisition**

Add:

```cpp
mutable ::std::atomic_bool m_bDestinationGraphicsLeaseActive{false};

::draw2d::graphics_lease acquire_graphics(::draw2d::host * pdraw2dhost = nullptr);
bool try_begin_destination_graphics_lease() const;
void end_destination_graphics_lease() const;
bool has_active_destination_graphics_lease() const;
```

`acquire_graphics()` resolves a null host from the main interaction when possible, CAS-acquires the image flag, and calls the system draw2d service. If pool acquisition throws, clear the flag before rethrowing. `graphics_lease::close()` must clear the image flag after backend release and before returning the graphics to idle storage.

- [ ] **Step 3: Guard conflicting operations**

Before base image destruction and before CPU/GPU `map()`, throw `error_wrong_state` if a destination lease is active. Add the same guard to GPU image create/resize entry points touched by the current NanoVG path. Do not guard source sampling after the lease has been released; the backend fence handles that transition.

- [ ] **Step 4: Run GREEN and build `aura` plus `bred`**

Run the extended contract, the existing GPU image mapping/lifecycle contracts, and build `aura` then `bred`. Expected: all exit `0`.

- [ ] **Step 5: Commit Task 3**

Commit only the four Task 3 files in `source/app` with:

```text
Add exclusive image graphics acquisition
```

### Task 4: Warm GPU Graphics and NanoVG Target Rebinding

**Files:**
- Modify: `source/app/bred/gpu/graphics.h`
- Modify: `source/app/bred/gpu/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/image.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/image.cpp`
- Create: `source/app-graphics3d/draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp`

**Interfaces:**
- Consumes: Tasks 1–3 leases and acquisition hooks.
- Produces: warm context retention, one NanoVG context per pooled graphics, and safe image-target fence/unbind.

- [ ] **Step 1: Write the failing NanoVG integration contract**

Assert:

```cpp
assert(gpuGraphicsHeader.find("::gpu::context_lease m_contextlease") != std::string::npos);
assert(nanovgCreate.find("acquire_draw2d_context") != std::string::npos);
assert(nanovgCreate.find("create_draw2d_context") == std::string::npos);
assert(nanovgHeader.find("on_acquire_memory_graphics") != std::string::npos);
assert(nanovgHeader.find("on_release_memory_graphics") != std::string::npos);
assert(nanovgRelease.find("defer_fence") != std::string::npos);
assert(nanovgRelease.find("m_pimage = nullptr") != std::string::npos);
```

Run RED from `source/app-graphics3d`.

- [ ] **Step 2: Give GPU graphics warm context ownership**

Add `::gpu::context_lease m_contextlease;` to `gpu::graphics`. Add:

```cpp
void set_context_lease(::gpu::context_lease && contextlease);
::gpu::context_lease & context_lease();
```

`set_context_lease()` stores the lease and calls `set_gpu_context(m_contextlease.get())`. GPU graphics destruction clears its compositor association before closing the context lease. Returning a graphics object to the draw2d pool does not close this member.

- [ ] **Step 3: Acquire pooled contexts in NanoVG memory graphics creation**

In `_create_memory_graphics(size)`, replace direct `create_draw2d_context()` with:

```cpp
auto contextlease = pgpudevice->acquire_draw2d_context(
   ::gpu::e_output_gpu_buffer,
   size);
set_context_lease(::transfer(contextlease));
auto pgpucontextNew = gpu_context();
pgpucontextNew->m_pgpucompositor = this;
```

Create `m_pdc` once when the graphics object itself is created. Do not delete/recreate `m_pdc` when the graphics object merely changes target images.

- [ ] **Step 4: Implement NanoVG lease hooks**

Override the acquisition hook to call the base hook, synchronously resize the context when needed, set the output transform for the target size, and start one offscreen draw layer/frame.

Override release to end the layer/frame if open, call `glFlush`, add `defer_fence()` to the bound GPU image texture, then invoke the base release hook. If any step throws, mark the graphics/context damaged through the active lease return path.

Legacy `_get_graphics()` remains available but must not be called by the migrated font path.

- [ ] **Step 5: Run GREEN and build affected targets**

Run the new contract plus existing `memory_graphics_lifecycle_test`, `gpu_image_lifecycle_test`, and `gpu_image_fast_path_test`. Build `bred`, `gpu_opengl`, and `draw2d_nanovg` Debug/x64. Expected: all exit `0`.

- [ ] **Step 6: Commit repository boundaries separately**

Commit `bred/gpu/graphics.*` in `source/app` with:

```text
Retain pooled GPU context leases in graphics
```

Commit NanoVG files/tests in `source/app-graphics3d` with:

```text
Reuse NanoVG graphics across image targets
```

### Task 5: Single-Lease Font Measurement and Leased Preview Rendering

**Files:**
- Modify: `source/app/aura/graphics/write_text/font_list.h`
- Modify: `source/app/aura/graphics/write_text/font_list.cpp`
- Modify: `source/app/aura/graphics/write_text/text_box.cpp`
- Create: `source/app/aura/graphics/write_text/tests/font_enumeration_graphics_lease_contract_test.cpp`

**Interfaces:**
- Consumes: measurement and image graphics leases from Tasks 2–4.
- Produces: one measurement graphics/context bundle per enumeration and short preview leases.

- [ ] **Step 1: Write the failing font vertical-slice contract**

Extract the `font_list::update_extents()` and `text_box::update()` sections and assert:

```cpp
assert(updateExtents.find("acquire_memory_graphics") != std::string::npos);
assert(updateExtents.find("fork_count") == std::string::npos);
assert(updateExtents.find("create_memory_graphics") == std::string::npos);
assert(updateExtents.find("update_extents(pfontlistdata, plistitem, pgraphics") != std::string::npos);
assert(textBoxUpdate.find("acquire_graphics") != std::string::npos);
assert(textBoxUpdate.find("m_pimage->g()") == std::string::npos);
assert(source.find("[gpu.performance.font_enumeration]") != std::string::npos);
```

- [ ] **Step 2: Run RED**

Compile/run from `source/app`. Expected: abort at the first new assertion.

- [ ] **Step 3: Make extent calculation accept a borrowed graphics pointer**

Change the helper signature to:

```cpp
void update_extents(
   font_list_data * pfontlistdata,
   font_list_item * pitem,
   ::draw2d::graphics * pgraphics,
   ::collection::index iBox);
```

Remove its lazy `create_memory_graphics()` block. Require a non-null graphics pointer and keep font creation, character-set checks, and extent calls on that graphics context.

- [ ] **Step 4: Replace the two `fork_count()` GPU phases with one background enumeration task**

Keep `update_extents()` asynchronous by using one `m_papplication->fork(...)`. Inside the task:

1. acquire one 256x256 measurement graphics lease;
2. process every item for box zero in index order, preserving serial/restart checks;
3. process remaining boxes with the same `graphicslease.get()`;
4. call `layout()`; and
5. allow the lease to return at task exit.

Do not retain a lease in each `font_list_item` or `text_box`.

- [ ] **Step 5: Migrate preview rendering to a short destination lease**

In `text_box::update()`, replace all repeated `m_pimage->g()` calls with one scope:

```cpp
auto pdraw2dhost = plist->m_puserinteractionGraphicsContext
   ? (::draw2d::host *)plist->m_puserinteractionGraphicsContext.m_p
   : (::draw2d::host *)plist->m_puserinteraction.m_p;
auto graphicslease = m_pimage->acquire_graphics(pdraw2dhost);
graphicslease->set_alpha_mode(::draw2d::e_alpha_mode_set);
graphicslease->fill_rectangle(::i32_rectangle(m_size), uBackgroundColor);
graphicslease->set_alpha_mode(::draw2d::e_alpha_mode_blend);
graphicslease->set(m_pfont);
graphicslease->set_text_color(uForegroundColor);
graphicslease->set_text_rendering_hint(::write_text::e_rendering_anti_alias);
graphicslease->text_out(
   plist->m_rectangleMargin.left,
   plist->m_rectangleMargin.top,
   scopedstrText);
graphicslease.close();
```

Set `m_bOk` only after successful close so an incomplete texture is never cached as a valid preview.

- [ ] **Step 6: Add enumeration diagnostics**

Under the existing application flag, measure and report:

```text
[gpu.performance.font_enumeration] total_us=... graphics_acquire_us=... fonts_created=... font_create_us=... extent_queries=... extent_us=... measurement_graphics=... contexts_expected=1
```

Load the enabled flag once at task start. When disabled, skip all clocks and counters.

- [ ] **Step 7: Run GREEN and build `aura`**

Run the new test and existing font-list diagnostics contract, then build `aura`. Expected: all exit `0`.

- [ ] **Step 8: Commit Task 5**

Commit only the four font files/tests in `source/app` with:

```text
Reuse one graphics lease during font enumeration
```

### Task 6: Integrated Verification and Runtime Evidence

**Files:**
- Verify all Task 1–5 files.
- Build: `solution-windows/SceneFoundry.sln`, target `shared_app_graphics3d_continuum`.

**Interfaces:**
- Consumes: the complete pooled vertical slice.
- Produces: build and runtime evidence that resource count no longer follows fonts/images/CPU affinity.

- [ ] **Step 1: Run all focused contracts freshly**

Compile/run:

```text
bred/gpu/tests/context_lease_pool_contract_test.cpp
aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp
aura/graphics/write_text/tests/font_enumeration_graphics_lease_contract_test.cpp
draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp
bred/gpu/tests/gpu_image_mapping_contract_test.cpp
draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp
draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp
```

Expected: every executable exits `0` from its required nested-repository working directory.

- [ ] **Step 2: Inspect repository boundaries and CRLF**

Run `git status --short` and `git diff --check` in the root and both nested repositories. Verify every modified/new C++ file has no bare LF and confirm unrelated user files remain unstaged.

- [ ] **Step 3: Build Continuum**

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: exit `0` with no new compile/link errors.

- [ ] **Step 4: Run the evidence scenario**

Enable existing diagnostics at a 1,000 ms interval, start Continuum with on-screen OpenGL/NanoVG rendering, open the font list, wait for enumeration, and scroll continuously for at least ten seconds. Capture:

```text
[gpu.context_pool]
[draw2d.graphics_pool]
[gpu.performance.font_enumeration]
[gpu.performance.nanovg_image]
[gpu.performance.image_mapping]
```

Expected architecture evidence:

- font measurement reports one measurement graphics/context;
- context/graphics creation does not scale with font count or CPU affinity;
- preview rendering reuses idle graphics;
- `cpu_fallbacks=0` and no mapping bytes during list drawing;
- font previews retain correct transparency/colors; and
- the UI remains responsive during enumeration and scrolling.

- [ ] **Step 5: Stop on evidence mismatch**

If context creations still scale with affinity, if previews map to CPU, or if color/transparency regresses, do not apply another optimization. Preserve the logs and return to root-cause investigation for that single failed boundary.

- [ ] **Step 6: Leave root nested-repository integration unstaged**

Do not stage root nested-repository pointers until the user reviews the runtime evidence and explicitly requests integration.

---

## Follow-Up Plan Boundary

After this vertical slice is verified, write a separate implementation plan for the approved repository-wide API migration:

- rename `image::g()` to `g2()` to create the deliberate compile break;
- migrate destination drawing to `acquire_graphics()` module by module;
- replace source-graphics arguments with image/texture arguments;
- migrate genuinely persistent users to member `graphics_lease`; and
- finally remove legacy `m_pgraphics`, `get_graphics()`, `_get_graphics()`, and `g2()`.

Keeping that migration separate prevents an 800-call, multi-platform compatibility rewrite from obscuring whether the pool/font architecture itself works.
