# Raster Font Backend Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent NanoVG font enumeration from including Windows raster-only fonts such as `Courier` while preserving them for raster-capable draw2d backends.

**Architecture:** Aura exposes a virtual draw2d raster-font capability that defaults to enabled. NanoVG overrides it to disabled. `write_text_win32::font_enumeration` reads the active backend capability before `EnumFontFamiliesW` and disables its existing raster branch at the enumeration source.

**Tech Stack:** C++20, ca2 Aura draw2d/write_text interfaces, Windows GDI `EnumFontFamiliesW`, NanoVG, MSBuild Debug/x64.

## Global Constraints

- Preserve existing line endings when practical and use CRLF for modified C++ and Markdown files.
- Do not hardcode font substitutions such as `Courier` to `Courier New`.
- Do not type-check or cast the active backend to `draw2d_nanovg` from Aura or `write_text_win32`.
- Keep TrueType and other non-raster enumeration behavior unchanged.
- Preserve unrelated dirty OpenGL and NanoVG diagnostics changes.

---

### Task 1: Aura Raster-Font Capability

**Files:**
- Modify: `source/app/aura/graphics/draw2d/draw2d.h`
- Modify: `source/app/aura/graphics/draw2d/draw2d.cpp`
- Create: `source/app/aura/graphics/write_text/tests/raster_font_capability_contract_test.cpp`

**Interfaces:**
- Produces: `virtual bool ::draw2d::draw2d::write_text_supports_raster_fonts()`
- Default result: `true`

- [ ] **Step 1: Write the failing Aura contract**

Create a standalone source contract that reads the draw2d header and source:

```cpp
const auto header = read_file("aura/graphics/draw2d/draw2d.h");
const auto source = read_file("aura/graphics/draw2d/draw2d.cpp");

assert(header.find("virtual bool write_text_supports_raster_fonts();") != std::string::npos);
assert(source.find("bool draw2d::write_text_supports_raster_fonts()") != std::string::npos);
assert(source.find("return true;") != std::string::npos);
```

- [ ] **Step 2: Run the contract and verify RED**

Run from `source/app`:

```powershell
g++ aura\graphics\write_text\tests\raster_font_capability_contract_test.cpp -std=c++17 -o $env:TEMP\raster_font_capability_contract_test.exe
& $env:TEMP\raster_font_capability_contract_test.exe
```

Expected: assertion failure because the virtual capability is absent.

- [ ] **Step 3: Add the Aura default capability**

Add to `draw2d.h` near the existing graphics-context capability methods:

```cpp
virtual bool write_text_supports_raster_fonts();
```

Add to `draw2d.cpp`:

```cpp
bool draw2d::write_text_supports_raster_fonts()
{

   return true;

}
```

- [ ] **Step 4: Verify GREEN and build Aura**

Run the contract again and rebuild `source/app/aura/aura.vcxproj` with Debug/x64. Expected: contract exit code 0 and `aura.dll` produced without errors.

- [ ] **Step 5: Commit Aura changes**

```powershell
git -C source\app add -- aura/graphics/draw2d/draw2d.h aura/graphics/draw2d/draw2d.cpp aura/graphics/write_text/tests/raster_font_capability_contract_test.cpp
git -C source\app commit -m "feat: expose raster font backend capability"
```

### Task 2: NanoVG Capability Override

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/font_context_registration_contract_test.cpp`

**Interfaces:**
- Consumes: `virtual bool ::draw2d::draw2d::write_text_supports_raster_fonts()`
- Produces: `bool draw2d_nanovg::draw2d::write_text_supports_raster_fonts() override`
- NanoVG result: `false`

- [ ] **Step 1: Extend the NanoVG contract and verify RED**

Add assertions:

```cpp
assert(header.find("write_text_supports_raster_fonts() override") != std::string::npos);
assert(source.find("bool draw2d::write_text_supports_raster_fonts()") != std::string::npos);
assert(source.find("return false;") != std::string::npos);
```

Compile and run `font_context_registration_contract_test.cpp` from `source/app-graphics3d`. Expected: assertion failure for the missing override.

- [ ] **Step 2: Implement the NanoVG override**

Add to `draw2d_nanovg/draw2d.h`:

```cpp
bool write_text_supports_raster_fonts() override;
```

Add to `draw2d_nanovg/draw2d.cpp`:

```cpp
bool draw2d::write_text_supports_raster_fonts()
{

   return false;

}
```

- [ ] **Step 3: Verify GREEN and build NanoVG**

Run the contract again and rebuild `draw2d_nanovg.vcxproj` with Debug/x64. Expected: contract exit code 0 and `draw2d_nanovg.dll` produced without errors.

- [ ] **Step 4: Commit only the capability hunks**

Stage the two draw2d files and the contract. If these files contain unrelated worktree edits, use selective staging and verify the cached diff before committing:

```powershell
git -C source\app-graphics3d commit -m "feat: disable raster font enumeration for NanoVG"
```

### Task 3: Windows Enumeration Filter

**Files:**
- Modify: `operating_system/operating_system-windows/write_text_win32/font_enumeration.cpp`
- Create: `operating_system/operating_system-windows/write_text_win32/tests/font_enumeration_capability_contract_test.cpp`

**Interfaces:**
- Consumes: `system()->draw2d()->write_text_supports_raster_fonts()`
- Uses existing flag: `::write_text::font_enumeration::m_bRaster`

- [ ] **Step 1: Write the failing Windows enumeration contract**

Create a source contract that isolates `on_enumerate_fonts()` and asserts ordering:

```cpp
const auto capability = enumerate.find("write_text_supports_raster_fonts()");
const auto disableRaster = enumerate.find("m_bRaster = false", capability);
const auto enumFonts = enumerate.find("EnumFontFamiliesW", disableRaster);

assert(capability != std::string::npos);
assert(disableRaster != std::string::npos);
assert(enumFonts != std::string::npos);
assert(capability < disableRaster && disableRaster < enumFonts);
```

- [ ] **Step 2: Run the contract and verify RED**

Compile and run from `operating_system`. Expected: assertion failure because the Windows enumerator does not consult the backend capability.

- [ ] **Step 3: Apply the capability before GDI enumeration**

In `font_enumeration::on_enumerate_fonts()`, before `EnumFontFamiliesW`, add:

```cpp
if (!system()->draw2d()->write_text_supports_raster_fonts())
{

   m_bRaster = false;

}
```

Include the Aura draw2d declaration if the current framework includes do not provide a complete type.

- [ ] **Step 4: Verify GREEN and build write_text_win32**

Run the new contract and the existing `font_face_resolver_contract_test`, then rebuild `write_text_win32.vcxproj` with Debug/x64. Expected: both contracts exit 0 and `write_text_win32.dll` links without errors.

- [ ] **Step 5: Commit Windows filtering**

```powershell
git -C operating_system\operating_system-windows add -- write_text_win32/font_enumeration.cpp write_text_win32/tests/font_enumeration_capability_contract_test.cpp
git -C operating_system\operating_system-windows commit -m "fix: filter unsupported Windows raster fonts"
```

### Task 4: Integrated Verification

**Files:**
- Verify only; no production edits expected.

**Interfaces:**
- Validates the complete capability flow from Aura through NanoVG into Windows enumeration.

- [ ] **Step 1: Run all capability and font contracts**

Run the Aura raster capability contract, NanoVG font-context contract, Windows enumeration capability contract, and Windows font-face resolver contract. Expected: four PASS results.

- [ ] **Step 2: Rebuild the integrated Debug/x64 targets**

Rebuild, in dependency order:

1. `source/app/aura/aura.vcxproj`
2. `operating_system/operating_system-windows/write_text_win32/write_text_win32.vcxproj`
3. `source/app-graphics3d/draw2d_nanovg/draw2d_nanovg.vcxproj`
4. `source/app-graphics3d/continuum/__implement/shared_app_graphics3d_continuum.vcxproj`

Expected: all four targets build without MSBuild errors.

- [ ] **Step 3: Audit repository state**

Run `git diff --check` in each modified repository and confirm unrelated OpenGL and NanoVG diagnostic files remain unstaged.

- [ ] **Step 4: Runtime validation handoff**

Run the continuum application with NanoVG. Expected: font enumeration passes the former `Courier` position without a NanoVG loading exception, `Courier` is absent from the NanoVG-backed font list, and outline-font previews continue to render.
