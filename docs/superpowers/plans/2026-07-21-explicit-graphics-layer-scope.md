# Explicit Graphics Layer Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pooled graphics leases passive resource owners and move preview rendering into an explicit, exception-safe layer scope that cannot present the window swap chain.

**Architecture:** Aura provides a move-only `draw2d::graphics_layer_scope` nested inside a live `draw2d::graphics_lease`. Bred's GPU graphics override saves and restores the thread-local GPU layer. NanoVG pool hooks only bind, flush, fence, and unbind; font measurement opens no layer, while preview rendering explicitly opens one non-closing layer scope.

**Tech Stack:** C++20, SceneFoundry Aura/Bred, GPU layer abstraction, NanoVG GL3/OpenGL, MSVC source-contract tests, Visual Studio/MSBuild.

## Global Constraints

- Preserve unrelated root and nested-repository changes; stage only files named by the active task.
- Use Windows CRLF for every modified or new C++ source/header.
- Both RAII types are move-only and have non-throwing destructors plus explicit `close()`.
- Graphics lease acquire/release hooks must not start or end a device frame or GPU layer.
- A layer scope always calls `end_layer(false)` and never presents a swap chain.
- The containing on-screen draw remains the device-frame owner.
- Font measurement uses one graphics lease and no layer scope.
- Preview cache validity is set only after both closes succeed.
- Preserve the NanoVG GPU-only image path and introduce no CPU mapping.

---

## File Structure

### `source/app`

- Create `aura/graphics/draw2d/graphics_layer_scope.h/.cpp` for the RAII transaction.
- Modify `aura/graphics/draw2d/graphics_lease.h/.cpp` for scope creation and active-scope tracking.
- Modify `aura/graphics/draw2d/graphics.h/.cpp` for backend-neutral scope hooks.
- Register the new files in `aura/aura.vcxproj` and `.filters`.
- Extend `aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp`.
- Modify `bred/gpu/graphics.h/.cpp` and add `bred/gpu/tests/gpu_graphics_layer_scope_contract_test.cpp` for GPU layer restoration.
- Modify `aura/graphics/write_text/text_box.cpp` and its font contract for explicit preview scope use.

### `source/app-graphics3d`

- Modify `draw2d_nanovg/graphics.h/.cpp` to remove frame/layer ownership from pool hooks.
- Modify `draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp` to enforce passive hooks.

---

### Task 1: Backend-Neutral Graphics Layer Scope

**Files:**
- Create: `source/app/aura/graphics/draw2d/graphics_layer_scope.h`
- Create: `source/app/aura/graphics/draw2d/graphics_layer_scope.cpp`
- Modify: `source/app/aura/graphics/draw2d/graphics_lease.h`
- Modify: `source/app/aura/graphics/draw2d/graphics_lease.cpp`
- Modify: `source/app/aura/graphics/draw2d/graphics.h`
- Modify: `source/app/aura/graphics/draw2d/graphics.cpp`
- Modify: `source/app/aura/aura.vcxproj`
- Modify: `source/app/aura/aura.vcxproj.filters`
- Modify: `source/app/aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp`

**Interfaces:**
- Consumes: `graphics::start_layer(bool)`, `graphics::end_layer(bool)`, and `graphics_lease::mark_damaged()`.
- Produces: `graphics_layer_scope`, `graphics_lease::begin_layer_scope()`, and virtual scope hooks.

- [ ] **Step 1: Extend the contract and run RED**

Read the new header/source and assert:

```cpp
assert(scopeHeader.find("graphics_layer_scope(const graphics_layer_scope &) = delete;") != std::string::npos);
assert(scopeHeader.find("graphics_layer_scope(graphics_layer_scope &&") != std::string::npos);
assert(scopeHeader.find("void close();") != std::string::npos);
assert(scopeSource.find("on_begin_layer_scope") != std::string::npos);
assert(scopeSource.find("on_end_layer_scope") != std::string::npos);
assert(scopeSource.find("mark_damaged") != std::string::npos);
assert(leaseHeader.find("graphics_layer_scope begin_layer_scope();") != std::string::npos);
assert(leaseHeader.find("m_bLayerScopeActive") != std::string::npos);
assert(leaseSource.find("cannot close a graphics lease with an active layer scope") != std::string::npos);
assert(graphicsHeader.find("virtual void on_begin_layer_scope();") != std::string::npos);
assert(graphicsHeader.find("virtual void on_end_layer_scope();") != std::string::npos);
```

Compile/run from `source/app` with MSVC. Expected: assertion failure because the scope is absent.

- [ ] **Step 2: Create the move-only scope**

Use this interface in `graphics_layer_scope.h`:

```cpp
namespace draw2d
{
   class graphics_lease;
   class CLASS_DECL_AURA graphics_layer_scope
   {
   public:
      ::draw2d::graphics_lease * m_pgraphicslease = nullptr;
      ::draw2d::graphics_pointer m_pgraphics;
      bool m_bOpen = false;

      graphics_layer_scope();
      explicit graphics_layer_scope(::draw2d::graphics_lease & graphicslease);
      graphics_layer_scope(const graphics_layer_scope &) = delete;
      graphics_layer_scope & operator=(const graphics_layer_scope &) = delete;
      graphics_layer_scope(graphics_layer_scope && scope) noexcept;
      graphics_layer_scope & operator=(graphics_layer_scope && scope) noexcept;
      ~graphics_layer_scope() noexcept;
      explicit operator bool() const;
      void close();
      void close_noexcept() noexcept;
   };
}
```

The constructor calls lease tracking and `on_begin_layer_scope()`. If begin throws, clear tracking before rethrowing. `close()` detaches open state first, calls `on_end_layer_scope()`, always clears tracking, and marks the lease damaged before rethrowing a backend failure. The destructor calls `close_noexcept()`.

- [ ] **Step 3: Add lease tracking and factory**

Add to `graphics_lease.h`:

```cpp
bool m_bLayerScopeActive = false;
::draw2d::graphics_layer_scope begin_layer_scope();
void _begin_layer_scope();
void _end_layer_scope();
bool has_active_layer_scope() const;
```

Implement exact state rules:

```cpp
void graphics_lease::_begin_layer_scope()
{
   if (!m_pgraphics || m_bLayerScopeActive)
      throw ::exception(error_wrong_state, "graphics lease cannot begin another layer scope");
   m_bLayerScopeActive = true;
}

void graphics_lease::_end_layer_scope()
{
   m_bLayerScopeActive = false;
}
```

`begin_layer_scope()` returns `graphics_layer_scope(*this)`. At the start of explicit `close()`, mark damaged and throw `error_wrong_state` with `"cannot close a graphics lease with an active layer scope"` if active. Add debug assertions preventing lease moves while a scope is active.

- [ ] **Step 4: Add backend-neutral hooks**

Add virtual methods to `draw2d::graphics`:

```cpp
virtual void on_begin_layer_scope();
virtual void on_end_layer_scope();
```

Base implementations call `start_layer(false)` and `end_layer(false)` respectively. They never call frame lifecycle methods.

- [ ] **Step 5: Register, normalize, test, and build**

Register the new files beside `graphics_lease` in both Aura project files. Run `unix2dos` on changed/new C++ files, rerun the contract, then build `aura` Debug/x64 with `/m:1 /nr:false`. Expected: test and build exit `0`.

- [ ] **Step 6: Commit Task 1**

Commit only Task 1 files in `source/app` as:

```text
feat: add explicit graphics layer scopes
```

### Task 2: Restore the Previous GPU Layer

**Files:**
- Modify: `source/app/bred/gpu/graphics.h`
- Modify: `source/app/bred/gpu/graphics.cpp`
- Create: `source/app/bred/gpu/tests/gpu_graphics_layer_scope_contract_test.cpp`

**Interfaces:**
- Consumes: Task 1 scope hooks.
- Produces: GPU-specific restoration without exposing `gpu::layer` to Aura.

- [ ] **Step 1: Write and run the failing contract**

Assert:

```cpp
assert(header.find("m_pgpulayerBeforeLayerScope") != std::string::npos);
assert(header.find("void on_begin_layer_scope() override;") != std::string::npos);
assert(header.find("void on_end_layer_scope() override;") != std::string::npos);
assert(source.find("::gpu::current_layer()") != std::string::npos);
assert(source.find("::gpu::set_current_layer") != std::string::npos);
assert(source.find("::draw2d::graphics::on_begin_layer_scope()") != std::string::npos);
assert(source.find("::draw2d::graphics::on_end_layer_scope()") != std::string::npos);
```

Compile/run from `source/app`. Expected: assertion failure.

- [ ] **Step 2: Implement GPU overrides**

Add:

```cpp
::pointer<::gpu::layer> m_pgpulayerBeforeLayerScope;
void on_begin_layer_scope() override;
void on_end_layer_scope() override;
```

Begin stores `::gpu::current_layer()` and calls the base hook. If begin throws, restore/release the saved pointer. End transfers the saved pointer locally, calls the base end hook, and restores `::gpu::set_current_layer(previous)` on both success and exception before rethrowing.

- [ ] **Step 3: Test, build Bred, and commit**

Normalize files, run the new contract, build `bred` Debug/x64, and commit only these files as:

```text
fix: restore GPU layer after scoped drawing
```

### Task 3: Make NanoVG Pool Hooks Passive

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp`

**Interfaces:**
- Consumes: Tasks 1-2 explicit scope lifecycle.
- Produces: pool hooks limited to bind, flush, fence, and unbind.

- [ ] **Step 1: Replace the temporary test and run RED**

Remove assertions specifically expecting `end_layer(false)` and assert:

```cpp
assert(nanovgAcquire.find("start_frame(") == std::string::npos);
assert(nanovgAcquire.find("start_layer(") == std::string::npos);
assert(nanovgRelease.find("end_layer(") == std::string::npos);
assert(nanovgRelease.find("end_frame(") == std::string::npos);
assert(nanovgRelease.find("defer_fence") != std::string::npos);
assert(nanovgRelease.find("m_pimage = nullptr") != std::string::npos);
```

Run the contract. Expected: failure because the hooks still own lifecycle.

- [ ] **Step 2: Remove lifecycle ownership**

Delete `m_bMemoryGraphicsLeaseFrameOpen` and `m_bMemoryGraphicsLeaseLayerOpen`. Keep acquisition binding, sizing, context selection, compositor assignment, and resize, but remove `start_frame()` and `start_layer(true)`. Keep release flush, error check, fence, base reset, and unbind, but remove both end calls.

- [ ] **Step 3: Test, build, and commit**

Normalize files; run the integration, image lifecycle, and memory graphics lifecycle contracts; build `gpu_opengl` and `draw2d_nanovg` Debug/x64. Commit only these files as:

```text
fix: keep rendering lifecycle outside graphics pool return
```

### Task 4: Put Font Preview Drawing Inside the Scope

**Files:**
- Modify: `source/app/aura/graphics/write_text/text_box.cpp`
- Modify: `source/app/aura/graphics/write_text/tests/font_enumeration_graphics_lease_contract_test.cpp`

**Interfaces:**
- Consumes: `graphics_lease::begin_layer_scope()`.
- Produces: exception-safe preview rendering nested inside its resource lease.

- [ ] **Step 1: Extend the font contract and run RED**

Assert:

```cpp
assert(updateExtents.find("begin_layer_scope") == std::string::npos);
assert(textBoxUpdate.find("auto layerscope = graphicslease.begin_layer_scope();") != std::string::npos);
assert(textBoxUpdate.find("layerscope.close();") != std::string::npos);
assert(textBoxUpdate.find("layerscope.close();") < textBoxUpdate.find("graphicslease.close();"));
```

Expected: failure because preview drawing lacks the explicit scope.

- [ ] **Step 2: Add the lexical scope**

Include `graphics_layer_scope.h`. Immediately after image graphics acquisition add:

```cpp
auto layerscope = graphicslease.begin_layer_scope();
```

After `text_out()` and before lease close add:

```cpp
layerscope.close();
graphicslease.close();
```

Keep `m_bOk = true` after both closes.

- [ ] **Step 3: Test, build, and commit**

Normalize both files; run both font contracts; build `aura` and `shared_app_graphics3d_continuum` Debug/x64. Commit only these files in `source/app` as:

```text
fix: scope font preview layer rendering explicitly
```

### Task 5: Integrated Verification and Runtime Resume

**Files:**
- Verify all Task 1-4 files.

**Interfaces:**
- Consumes: the complete explicit-scope correction.
- Produces: automated and runtime evidence.

- [ ] **Step 1: Run 7 focused contracts freshly**

Run:

```text
aura/graphics/draw2d/tests/graphics_lease_pool_contract_test.cpp
bred/gpu/tests/gpu_graphics_layer_scope_contract_test.cpp
aura/graphics/write_text/tests/font_enumeration_graphics_lease_contract_test.cpp
draw2d_nanovg/tests/graphics_lease_integration_contract_test.cpp
draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp
draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp
```

Expected: 7/7 exit `0`.

- [ ] **Step 2: Inspect boundaries and line endings**

Run `git status --short` and `git diff --check` in root and both nested repositories. Verify changed/new C++ files have no bare LF and unrelated root changes remain unstaged.

- [ ] **Step 3: Build Continuum freshly**

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: exit `0` with no new compile/link errors.

- [ ] **Step 4: Repeat runtime validation**

Run on-screen OpenGL/NanoVG, let font enumeration finish, and scroll for ten seconds. Require no OpenGL 1282 or lease-triggered swap-chain presentation, `measurement_graphics=1`, `contexts_expected=1`, `cpu_fallbacks=0`, no steady-state image mapping, correct transparent previews, and responsive scrolling. Preserve logs and stop at the first failed boundary.
