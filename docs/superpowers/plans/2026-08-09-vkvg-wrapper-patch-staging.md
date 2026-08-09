# VKVG Wrapper Patch Staging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the verified SceneFoundry VKVG fixes out of the vendored submodule and make both Visual Studio and CMake compile identical patched sources staged in their build-intermediate directories.

**Architecture:** The `port-vkvg` wrapper owns a manifest, a numbered unified patch series, and one CMake-script materializer. The materializer copies three affected pristine sources into a dedicated intermediate tree and applies the series with `git apply`; `vkvg.vcxproj` and the wrapper `CMakeLists.txt` replace only those source entries with generated paths.

**Tech Stack:** C11, CMake 3.16 script mode, Git unified patches, MSBuild/Visual C++, CTest-style CMake contract scripts, existing standalone C++17 contract tests.

## Global Constraints

- Preserve existing line endings when practical.
- Use Windows CRLF line endings for new and modified source files.
- Keep CMake files and unified patches using LF line endings.
- Never write generated patched sources into `port/graphics3d/vkvg/vkvg`.
- Keep the VKVG submodule pinned at `65d1eecacbfeb0f7a288896cccb8e1e871ecf6cf` during this migration.
- Remove the VKVG `branch = master` tracking hint; the parent mode-`160000` gitlink is the only revision selector.
- Preserve unrelated user changes in every enclosing repository.
- Restore only the exact VKVG files whose current changes have been represented by wrapper patches or wrapper-owned tests.

---

### Task 1: Materialize the fullscreen-state patch

**Files:**
- Modify: `port/graphics3d/vkvg/.gitmodules`
- Create: `port/graphics3d/vkvg/patches/vkvg_patch_manifest.cmake`
- Create: `port/graphics3d/vkvg/patches/materialize_vkvg_sources.cmake`
- Create: `port/graphics3d/vkvg/patches/0001-clear-fullscreen-bit-before-indexed-draw.patch`
- Create: `port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake`

**Interfaces:**
- Consumes: `VKVG_SOURCE_DIR`, `VKVG_OUTPUT_DIR`, and `VKVG_PATCH_DIR` absolute `-D` paths.
- Produces: `${VKVG_OUTPUT_DIR}/src/vkvg_context_internal.c`, `${VKVG_OUTPUT_DIR}/src/vkvg_device.c`, `${VKVG_OUTPUT_DIR}/src/vkvg_device_internal.c`, and `${VKVG_OUTPUT_DIR}/vkvg-patches.stamp`.

- [ ] **Step 1: Write the failing materialization contract**

Create a script that hashes the three pristine inputs, invokes the wished-for materializer, checks the hashes again, and requires the staged indexed-draw function to clear and push `FULLSCREEN_BIT` before `CmdDrawIndexed`:

```cmake
cmake_minimum_required(VERSION 3.16)

foreach(required WRAPPER_DIR TEST_OUTPUT_DIR)
  if(NOT DEFINED ${required} OR "${${required}}" STREQUAL "")
    message(FATAL_ERROR "${required} is required")
  endif()
endforeach()

set(source_dir "${WRAPPER_DIR}/vkvg")
set(patch_dir "${WRAPPER_DIR}/patches")
set(materializer "${patch_dir}/materialize_vkvg_sources.cmake")
set(relative_sources
  src/vkvg_context_internal.c
  src/vkvg_device.c
  src/vkvg_device_internal.c)

file(REMOVE_RECURSE "${TEST_OUTPUT_DIR}")
foreach(relative IN LISTS relative_sources)
  string(MAKE_C_IDENTIFIER "${relative}" source_key)
  file(SHA256 "${source_dir}/${relative}" "before_${source_key}")
endforeach()

execute_process(
  COMMAND "${CMAKE_COMMAND}"
    "-DVKVG_SOURCE_DIR=${source_dir}"
    "-DVKVG_OUTPUT_DIR=${TEST_OUTPUT_DIR}"
    "-DVKVG_PATCH_DIR=${patch_dir}"
    -P "${materializer}"
  RESULT_VARIABLE result
  OUTPUT_VARIABLE output
  ERROR_VARIABLE error)
if(NOT result EQUAL 0)
  message(FATAL_ERROR "Materialization failed (${result})\n${output}\n${error}")
endif()

foreach(relative IN LISTS relative_sources)
  string(MAKE_C_IDENTIFIER "${relative}" source_key)
  file(SHA256 "${source_dir}/${relative}" "after_${source_key}")
  if(NOT "${before_${source_key}}" STREQUAL "${after_${source_key}}")
    message(FATAL_ERROR "Materialization modified pristine ${relative}")
  endif()
endforeach()

file(READ "${TEST_OUTPUT_DIR}/src/vkvg_context_internal.c" context_source)
string(FIND "${context_source}"
  "ctx->pushConsts.fsq_patternType &= ~FULLSCREEN_BIT;" clear_position)
string(FIND "${context_source}"
  "CmdDrawIndexed(ctx->cmd" draw_position)
if(clear_position EQUAL -1 OR draw_position EQUAL -1 OR clear_position GREATER draw_position)
  message(FATAL_ERROR "Ordinary indexed draws do not restore FULLSCREEN_BIT state")
endif()
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
$out = Join-Path $env:TEMP 'vkvg-patch-contract-red'
cmake -DWRAPPER_DIR=C:/Users/camilo/SceneFoundry/main/port/graphics3d/vkvg -DTEST_OUTPUT_DIR=$($out.Replace('\','/')) -P port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake
```

Expected: failure identifying the missing `patches/materialize_vkvg_sources.cmake`.

- [ ] **Step 3: Add the manifest**

Create:

```cmake
set(VKVG_PATCHED_RELATIVE_SOURCES
  src/vkvg_context_internal.c
  src/vkvg_device.c
  src/vkvg_device_internal.c)

set(VKVG_PATCH_FILES
  0001-clear-fullscreen-bit-before-indexed-draw.patch)
```

- [ ] **Step 4: Implement the minimal shared materializer**

Implement strict path validation, dedicated-output deletion, copy-only staging, ordered `git apply --check`, ordered `git apply`, and a final stamp:

```cmake
cmake_minimum_required(VERSION 3.16)

foreach(required VKVG_SOURCE_DIR VKVG_OUTPUT_DIR VKVG_PATCH_DIR)
  if(NOT DEFINED ${required} OR "${${required}}" STREQUAL "")
    message(FATAL_ERROR "${required} is required")
  endif()
endforeach()

get_filename_component(VKVG_SOURCE_DIR "${VKVG_SOURCE_DIR}" ABSOLUTE)
get_filename_component(VKVG_OUTPUT_DIR "${VKVG_OUTPUT_DIR}" ABSOLUTE)
get_filename_component(VKVG_PATCH_DIR "${VKVG_PATCH_DIR}" ABSOLUTE)
if(VKVG_OUTPUT_DIR STREQUAL VKVG_SOURCE_DIR OR
   VKVG_OUTPUT_DIR MATCHES "^${VKVG_SOURCE_DIR}(/|$)")
  message(FATAL_ERROR "VKVG_OUTPUT_DIR must be outside the pristine source tree")
endif()

include("${VKVG_PATCH_DIR}/vkvg_patch_manifest.cmake")
find_package(Git REQUIRED)
file(REMOVE_RECURSE "${VKVG_OUTPUT_DIR}")

foreach(relative IN LISTS VKVG_PATCHED_RELATIVE_SOURCES)
  if(NOT EXISTS "${VKVG_SOURCE_DIR}/${relative}")
    message(FATAL_ERROR "Missing pristine VKVG source: ${relative}")
  endif()
  get_filename_component(relative_directory "${relative}" DIRECTORY)
  file(MAKE_DIRECTORY "${VKVG_OUTPUT_DIR}/${relative_directory}")
  configure_file("${VKVG_SOURCE_DIR}/${relative}"
                 "${VKVG_OUTPUT_DIR}/${relative}" COPYONLY)
endforeach()

foreach(patch_name IN LISTS VKVG_PATCH_FILES)
  set(patch "${VKVG_PATCH_DIR}/${patch_name}")
  if(NOT EXISTS "${patch}")
    message(FATAL_ERROR "Missing VKVG wrapper patch: ${patch_name}")
  endif()
  execute_process(
    COMMAND "${GIT_EXECUTABLE}" apply --check --whitespace=nowarn "${patch}"
    WORKING_DIRECTORY "${VKVG_OUTPUT_DIR}"
    RESULT_VARIABLE check_result
    OUTPUT_VARIABLE check_output
    ERROR_VARIABLE check_error)
  if(NOT check_result EQUAL 0)
    message(FATAL_ERROR "VKVG patch check failed: ${patch_name}\n${check_output}\n${check_error}")
  endif()
  execute_process(
    COMMAND "${GIT_EXECUTABLE}" apply --whitespace=nowarn "${patch}"
    WORKING_DIRECTORY "${VKVG_OUTPUT_DIR}"
    RESULT_VARIABLE apply_result
    OUTPUT_VARIABLE apply_output
    ERROR_VARIABLE apply_error)
  if(NOT apply_result EQUAL 0)
    message(FATAL_ERROR "VKVG patch apply failed: ${patch_name}\n${apply_output}\n${apply_error}")
  endif()
endforeach()

file(WRITE "${VKVG_OUTPUT_DIR}/vkvg-patches.stamp" "materialized\n")
```

- [ ] **Step 5: Capture the verified fullscreen fix as patch 0001**

Generate a unified patch whose paths are `a/src/vkvg_context_internal.c` and `b/src/vkvg_context_internal.c` and whose only hunk inserts the clear plus `CmdPushConstants` immediately after `_ensure_renderpass_is_started(ctx)` in `_emit_draw_cmd_undrawn_vertices`.

- [ ] **Step 6: Run the contract and verify GREEN**

Run the Step 2 command.

Expected: exit 0, generated source present, pristine hashes unchanged.

- [ ] **Step 7: Commit Task 1 in the wrapper repository**

Before committing, extend the contract to read `.gitmodules`, reject any `branch =` entry, and verify the exact gitlink:

```cmake
file(READ "${WRAPPER_DIR}/.gitmodules" gitmodules)
if(gitmodules MATCHES "(^|[\r\n])[ \t]*branch[ \t]*=")
  message(FATAL_ERROR "VKVG submodule must be pinned only by its gitlink")
endif()

execute_process(
  COMMAND "${GIT_EXECUTABLE}" -C "${WRAPPER_DIR}" ls-files -s vkvg
  RESULT_VARIABLE gitlink_result
  OUTPUT_VARIABLE gitlink
  ERROR_VARIABLE gitlink_error
  OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT gitlink_result EQUAL 0 OR
   NOT gitlink MATCHES "^160000 65d1eecacbfeb0f7a288896cccb8e1e871ecf6cf 0[\t ]+vkvg$")
  message(FATAL_ERROR "Unexpected VKVG gitlink: ${gitlink}\n${gitlink_error}")
endif()
```

Run the contract and observe failure from the current `branch = master` line. Remove only that line from `.gitmodules`, rerun, and require GREEN.

Then commit:

```powershell
git -C port/graphics3d/vkvg add .gitmodules patches tests/vkvg_patch_materialization_contract.cmake
git -C port/graphics3d/vkvg commit -m "build: pin and stage patched vkvg sources"
```

---

### Task 2: Capture the remaining production fixes and wrapper rendering regression

**Files:**
- Create: `port/graphics3d/vkvg/patches/0002-fix-non-zero-fill-winding.patch`
- Create: `port/graphics3d/vkvg/patches/0003-honor-requested-sample-count.patch`
- Create: `port/graphics3d/vkvg/patches/0004-strengthen-render-pass-handoffs.patch`
- Create: `port/graphics3d/vkvg/tests/offscreen_regression.c`
- Modify: `port/graphics3d/vkvg/patches/vkvg_patch_manifest.cmake`
- Modify: `port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake`

**Interfaces:**
- Consumes: the Task 1 materializer and current verified diffs in the dirty VKVG submodule.
- Produces: one ordered patch per independent production behavior plus a wrapper-owned pixel regression program.

- [ ] **Step 1: Extend the contract with the remaining wished-for generated behavior**

Add generated-source assertions for:

```cmake
file(READ "${TEST_OUTPUT_DIR}/src/vkvg_context_internal.c" context_source)
file(READ "${TEST_OUTPUT_DIR}/src/vkvg_device.c" device_source)
file(READ "${TEST_OUTPUT_DIR}/src/vkvg_device_internal.c" device_internal_source)

foreach(required_text
  "float signedArea = 0.0f;"
  "ecp_zcross(v0, v2, v1) * signedArea < 0")
  string(FIND "${context_source}" "${required_text}" position)
  if(position EQUAL -1)
    message(FATAL_ERROR "Missing staged winding fix: ${required_text}")
  endif()
endforeach()

string(FIND "${device_source}"
  "if (!(counts & info->samples))" sample_guard)
string(FIND "${device_internal_source}"
  "VK_PIPELINE_STAGE_ALL_COMMANDS_BIT" all_commands_stage)
string(FIND "${device_internal_source}"
  "VK_ATTACHMENT_STORE_OP_STORE" multisample_store)
if(sample_guard EQUAL -1 OR all_commands_stage EQUAL -1 OR multisample_store EQUAL -1)
  message(FATAL_ERROR "Missing staged device/render-pass fixes")
endif()
```

- [ ] **Step 2: Run the contract and verify RED**

Run the Task 1 Step 2 command.

Expected: failure naming the first missing winding/device/render-pass behavior.

- [ ] **Step 3: Create patches 0002 through 0004 from the verified submodule diff**

Split the current production diff exactly by concern:

- `0002`: signed-area calculation and winding-independent ear selection in `src/vkvg_context_internal.c`.
- `0003`: supported requested sample count with 1× fallback in `src/vkvg_device.c`.
- `0004`: both external dependency arrays and multisample `storeOp` in `src/vkvg_device_internal.c`.

Update the manifest to list all four patches in numeric order.

- [ ] **Step 4: Move the reusable offscreen assertions into wrapper ownership**

Create `tests/offscreen_regression.c` from the current modified `vkvg/tests/offscreen.c`, retaining:

- transparent background assertion;
- opaque red solid-fill assertion;
- clockwise gradient top/bottom assertions;
- counterclockwise gradient top/bottom assertions;
- complete cleanup on every allocation or readback failure.

Write any PNG output under an optional command-line path; do not write `offscreen.png` into the source directory by default.

- [ ] **Step 5: Run the materialization contract and verify GREEN**

Expected: all generated-source checks pass and the pristine source hashes remain unchanged.

- [ ] **Step 6: Commit Task 2 in the wrapper repository**

```powershell
git -C port/graphics3d/vkvg add patches tests
git -C port/graphics3d/vkvg commit -m "fix: preserve vkvg rendering corrections"
```

---

### Task 3: Integrate staged sources into Visual Studio

**Files:**
- Modify: `port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake`
- Modify: `port/graphics3d/vkvg/vkvg.vcxproj`
- Modify: `port/graphics3d/vkvg/vkvg.vcxproj.filters`

**Interfaces:**
- Consumes: Task 1 materializer and manifest.
- Produces: MSBuild target `MaterializeVkvgPatchedSources` and generated `ClCompile` inputs under `$(IntDir)vkvg-patched\src`.

- [ ] **Step 1: Add failing Visual Studio integration assertions**

Read `vkvg.vcxproj` from the contract and require these stable markers:

```cmake
file(READ "${WRAPPER_DIR}/vkvg.vcxproj" vcxproj)
foreach(required_text
  "Name=\"MaterializeVkvgPatchedSources\""
  "BeforeTargets=\"ClCompile\""
  "$(IntDir)vkvg-patched\\src\\vkvg_context_internal.c"
  "$(IntDir)vkvg-patched\\src\\vkvg_device.c"
  "$(IntDir)vkvg-patched\\src\\vkvg_device_internal.c"
  "materialize_vkvg_sources.cmake")
  string(FIND "${vcxproj}" "${required_text}" position)
  if(position EQUAL -1)
    message(FATAL_ERROR "Visual Studio wrapper is missing: ${required_text}")
  endif()
endforeach()
```

Also reject direct `ClCompile Include="vkvg\src\..."` entries for the three affected files.

- [ ] **Step 2: Run the contract and verify RED**

Expected: failure reporting the missing `MaterializeVkvgPatchedSources` target.

- [ ] **Step 3: Add incremental MSBuild materialization**

Add properties for:

```xml
<VkvgPatchOutputDir>$(IntDir)vkvg-patched\</VkvgPatchOutputDir>
<VkvgPatchStamp>$(VkvgPatchOutputDir)vkvg-patches.stamp</VkvgPatchStamp>
<VkvgPatchCMakeExe Condition="'$(VkvgPatchCMakeExe)'==''">cmake</VkvgPatchCMakeExe>
```

Add an item list containing the materializer, manifest, four patches, and three pristine inputs. Add a target with those items as `Inputs`, the stamp plus three staged files as `Outputs`, and an `Exec` equivalent to:

```xml
<Exec Command="&quot;$(VkvgPatchCMakeExe)&quot; -DVKVG_SOURCE_DIR=&quot;$(ProjectDir)vkvg&quot; -DVKVG_OUTPUT_DIR=&quot;$(VkvgPatchOutputDir)&quot; -DVKVG_PATCH_DIR=&quot;$(ProjectDir)patches&quot; -P &quot;$(ProjectDir)patches\materialize_vkvg_sources.cmake&quot;" />
```

Replace exactly three direct `ClCompile` items with staged paths and give each a `Link` matching its original `vkvg\src\...` path.

- [ ] **Step 4: Update filters for the generated `ClCompile` identities**

Keep all three staged files displayed under `Source Files\vkvg\src`; remove filter entries whose `Include` no longer exists in the project.

- [ ] **Step 5: Run the contract and verify GREEN**

Expected: exit 0.

- [ ] **Step 6: Build the Visual Studio project**

Run:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
& $msbuild port\graphics3d\vkvg\vkvg.vcxproj /m /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir=C:\Users\camilo\SceneFoundry\main\solution-windows\ /v:minimal
```

Expected: exit 0 and compilation paths for the affected files point under the project intermediate directory.

- [ ] **Step 7: Commit Task 3 in the wrapper repository**

```powershell
git -C port/graphics3d/vkvg add vkvg.vcxproj vkvg.vcxproj.filters tests/vkvg_patch_materialization_contract.cmake
git -C port/graphics3d/vkvg commit -m "build: materialize vkvg patches in msbuild"
```

---

### Task 4: Integrate staged sources into CMake

**Files:**
- Modify: `port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake`
- Modify: `port/graphics3d/vkvg/CMakeLists.txt`

**Interfaces:**
- Consumes: the same manifest, materializer, patches, and pristine inputs as Visual Studio.
- Produces: generated affected sources included in both `vkvg` and `static_vkvg`, plus optional wrapper regression targets.

- [ ] **Step 1: Add failing CMake integration assertions**

Require the wrapper `CMakeLists.txt` to contain:

```cmake
include("${CMAKE_CURRENT_SOURCE_DIR}/patches/vkvg_patch_manifest.cmake")
add_custom_command(
set_source_files_properties(${VKVG_PATCHED_SOURCES} PROPERTIES GENERATED TRUE)
list(REMOVE_ITEM VKVG_SRC ${VKVG_PRISTINE_PATCHED_SOURCES})
list(APPEND VKVG_SRC ${VKVG_PATCHED_SOURCES})
```

Require both existing library declarations to consume the final `VKVG_SRC` list. Require a `VKVG_WRAPPER_BUILD_TESTS` option that adds `tests/offscreen_regression.c` only when enabled.

- [ ] **Step 2: Run the contract and verify RED**

Expected: failure reporting the missing CMake materialization command.

- [ ] **Step 3: Add one generated-source custom command**

After the original `FILE(GLOB VKVG_SRC ...)`, include the manifest, map relative inputs and outputs to absolute lists, remove pristine affected inputs from `VKVG_SRC`, append generated outputs, and add a custom command:

```cmake
include("${CMAKE_CURRENT_SOURCE_DIR}/patches/vkvg_patch_manifest.cmake")
set(VKVG_PATCH_OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/vkvg-patched")
set(VKVG_PATCHED_SOURCES)
set(VKVG_PRISTINE_PATCHED_SOURCES)
foreach(relative IN LISTS VKVG_PATCHED_RELATIVE_SOURCES)
  list(APPEND VKVG_PRISTINE_PATCHED_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/vkvg/${relative}")
  list(APPEND VKVG_PATCHED_SOURCES
    "${VKVG_PATCH_OUTPUT_DIR}/${relative}")
endforeach()

set(VKVG_PATCH_DEPENDENCIES)
foreach(patch_name IN LISTS VKVG_PATCH_FILES)
  list(APPEND VKVG_PATCH_DEPENDENCIES
    "${CMAKE_CURRENT_SOURCE_DIR}/patches/${patch_name}")
endforeach()

list(REMOVE_ITEM VKVG_SRC ${VKVG_PRISTINE_PATCHED_SOURCES})
list(APPEND VKVG_SRC ${VKVG_PATCHED_SOURCES})

add_custom_command(
  OUTPUT ${VKVG_PATCHED_SOURCES} "${VKVG_PATCH_OUTPUT_DIR}/vkvg-patches.stamp"
  COMMAND "${CMAKE_COMMAND}"
    "-DVKVG_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/vkvg"
    "-DVKVG_OUTPUT_DIR=${VKVG_PATCH_OUTPUT_DIR}"
    "-DVKVG_PATCH_DIR=${CMAKE_CURRENT_SOURCE_DIR}/patches"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/patches/materialize_vkvg_sources.cmake"
  DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/patches/materialize_vkvg_sources.cmake"
    "${CMAKE_CURRENT_SOURCE_DIR}/patches/vkvg_patch_manifest.cmake"
    ${VKVG_PATCH_DEPENDENCIES}
    ${VKVG_PRISTINE_PATCHED_SOURCES}
  VERBATIM)
set_source_files_properties(${VKVG_PATCHED_SOURCES} PROPERTIES GENERATED TRUE)
```

Keep the existing shared and static target declarations unchanged after `VKVG_SRC` is replaced, ensuring both consume identical generated inputs.

- [ ] **Step 4: Add opt-in wrapper regression targets**

Add:

```cmake
option(VKVG_WRAPPER_BUILD_TESTS "Build SceneFoundry VKVG wrapper regression tests" OFF)
if(VKVG_WRAPPER_BUILD_TESTS)
  enable_testing()
  add_test(
    NAME vkvg_patch_materialization_contract
    COMMAND "${CMAKE_COMMAND}"
      "-DWRAPPER_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
      "-DTEST_OUTPUT_DIR=${CMAKE_CURRENT_BINARY_DIR}/contract-vkvg-patched"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/vkvg_patch_materialization_contract.cmake")
  add_executable(vkvg_offscreen_regression tests/offscreen_regression.c)
  target_link_libraries(vkvg_offscreen_regression PRIVATE vkvg)
  add_test(NAME vkvg_offscreen_regression COMMAND vkvg_offscreen_regression)
endif()
```

- [ ] **Step 5: Run the standalone contract and verify GREEN**

Expected: exit 0.

- [ ] **Step 6: Configure and attempt the wrapper CMake build**

Run:

```powershell
$build = Join-Path $env:TEMP 'SceneFoundry-vkvg-cmake'
cmake -S port/graphics3d/vkvg -B $build -DVKVG_WRAPPER_BUILD_TESTS=ON
cmake --build $build --config Debug
ctest --test-dir $build -C Debug --output-on-failure
```

Expected: configure and materialization contract pass. If Vulkan, FreeType, shader tools, or another existing external dependency prevents a full library/test build, record the exact missing dependency while retaining a passing standalone materialization contract.

- [ ] **Step 7: Commit Task 4 in the wrapper repository**

```powershell
git -C port/graphics3d/vkvg add CMakeLists.txt tests/vkvg_patch_materialization_contract.cmake
git -C port/graphics3d/vkvg commit -m "build: materialize vkvg patches in cmake"
```

---

### Task 5: Restore the submodule and redirect existing contracts

**Files:**
- Modify: `source/app-graphics3d/draw2d_vkvg/tests/vkvg_fullscreen_push_constant_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_vkvg/tests/vkvg_render_pass_dependency_contract_test.cpp`
- Restore: `port/graphics3d/vkvg/vkvg/src/vkvg_context_internal.c`
- Restore: `port/graphics3d/vkvg/vkvg/src/vkvg_device.c`
- Restore: `port/graphics3d/vkvg/vkvg/src/vkvg_device_internal.c`
- Restore: `port/graphics3d/vkvg/vkvg/tests/offscreen.c`
- Restore line-ending-only status if present: `port/graphics3d/vkvg/vkvg/src/vkvg_context.c`

**Interfaces:**
- Consumes: verified staged outputs and wrapper patches from Tasks 1–4.
- Produces: clean VKVG submodule and contracts that validate wrapper ownership rather than local vendor edits.

- [ ] **Step 1: Change the existing contracts to require wrapper ownership**

For each production behavior, require:

- the pristine vendored function does not contain the SceneFoundry-only inserted block;
- the corresponding numbered patch contains the expected change;
- a fresh materialized output contains the expected change in executable order.

Retain the existing detailed assertions about push-constant ordering, dependency counts, access masks, sample fallback, and multisample storage.

- [ ] **Step 2: Compile and run the redirected contracts to verify RED**

Use the Visual Studio developer environment and compile both standalone tests with `/std:c++20 /EHsc` into a unique directory under `%TEMP%`.

Expected: failure because the vendored files still contain the local production changes.

- [ ] **Step 3: Prove the staged outputs preserve the current intentional diffs**

Materialize into a fresh temporary directory and compare each affected staged file against the current dirty vendored file after normalizing only CRLF/LF. Differences must be empty for the production source files before restoration.

Confirm `tests/offscreen_regression.c` contains the reusable assertions from dirty `vkvg/tests/offscreen.c`.

- [ ] **Step 4: Restore only the captured vendored files**

Run from the VKVG submodule after confirming the resolved paths are exactly under `port/graphics3d/vkvg/vkvg`:

```powershell
git restore --source=HEAD --worktree -- src/vkvg_context.c src/vkvg_context_internal.c src/vkvg_device.c src/vkvg_device_internal.c tests/offscreen.c
```

Expected: `git status --short` in the VKVG submodule is empty.

- [ ] **Step 5: Re-run the redirected contracts and verify GREEN**

Expected: both contracts exit 0.

- [ ] **Step 6: Rebuild VKVG through Visual Studio after restoration**

Run the Task 3 build command.

Expected: materialization occurs outside the submodule, VKVG builds successfully, and the submodule remains clean afterward.

- [ ] **Step 7: Commit redirected contracts in `app-graphics3d`**

```powershell
git -C source/app-graphics3d add draw2d_vkvg/tests/vkvg_fullscreen_push_constant_contract_test.cpp draw2d_vkvg/tests/vkvg_render_pass_dependency_contract_test.cpp
git -C source/app-graphics3d commit -m "test: validate staged vkvg wrapper patches"
```

---

### Task 6: Full verification and runtime regression

**Files:**
- Verify only; no production edits expected.

**Interfaces:**
- Consumes: completed Visual Studio and CMake patch integrations.
- Produces: fresh build, contract, cleanliness, and runtime evidence.

- [ ] **Step 1: Run wrapper and existing standalone contracts**

Compile and run:

- `queue_host_call_diagnostics_test.cpp`
- `queue_layer_handoff_contract_test.cpp`
- `vkvg_render_pass_dependency_contract_test.cpp`
- `gpu_layer_frame_handoff_contract_test.cpp`
- `swap_chain_present_handoff_contract_test.cpp`
- `swap_chain_output_order_contract_test.cpp`
- `path_line_continuity_contract_test.cpp`
- `gradient_pattern_lifetime_contract_test.cpp`
- `vkvg_fullscreen_push_constant_contract_test.cpp`

Expected: 9/9 pass, plus the standalone CMake materialization contract passes.

- [ ] **Step 2: Build all affected Debug x64 projects**

Build, with project references disabled and the solution directory supplied:

- `port/graphics3d/vkvg/vkvg.vcxproj`
- `source/app-graphics3d/draw2d_vkvg/draw2d_vkvg.vcxproj`
- `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj`
- `source/app/bred/bred.vcxproj`
- `source/app/experience_core/experience_core.vcxproj`

Expected: all exit 0; existing conversion warnings may remain but no errors.

- [ ] **Step 3: Re-run CMake verification**

Run Task 4 Step 6 in a fresh build directory. Run at least the materialization test even if an external dependency blocks the full build.

- [ ] **Step 4: Verify repository cleanliness boundaries**

Run:

```powershell
git -C port/graphics3d/vkvg/vkvg status --short
git -C port/graphics3d/vkvg diff --check
git -C source/app-graphics3d diff --check -- draw2d_vkvg/tests
```

Expected: VKVG submodule status empty and targeted diff checks exit 0.

- [ ] **Step 5: Verify the original visual symptom**

Launch `time-windows/x64/Debug/shared_app_graphics3d_continuum.exe`, wait until the seven-tab strip first appears, then hash a tightly cropped tab-strip capture for 600 samples at approximately 30 ms intervals.

Expected: one steady-state pixel hash with Options, GPU, hello_multiverse, switcher, Font, Color, and Open all present.

- [ ] **Step 6: Review final diffs and commits**

Confirm the wrapper repositories contain only the approved patch pipeline, production patch series, regression coverage, and build integrations. Confirm no generated staged source, PNG, object file, RenderDoc probe, or build directory is tracked.
