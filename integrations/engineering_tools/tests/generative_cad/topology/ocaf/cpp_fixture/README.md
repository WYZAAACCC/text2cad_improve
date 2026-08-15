# C++ OCCT fixture

用于在真实 C++ OCCT 下复现/验证 Python OCP 侧无法定位的 TNaming 原生问题。

## 环境

- MSVC 2022 Build Tools：`D:\vs`（`cl.exe` + Windows SDK 10.0.26100.0）
- conda 环境 `occt_cpp`：`occt 7.8.1` + `cmake` + `ninja`（conda-forge）
  - OCCT 头文件：`D:\anaconda\envs\occt_cpp\Library\include\opencascade`
  - OCCT 库：`D:\anaconda\envs\occt_cpp\Library\lib\TK*.lib`
  - OCCT DLL：`D:\anaconda\envs\occt_cpp\Library\bin\TK*.dll`

## 构建 + 运行（PowerShell）

```powershell
$src = 'E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\tests\generative_cad\topology\ocaf\cpp_fixture'
$build = "$src\build"
$prefix = 'D:\anaconda\envs\occt_cpp\Library'
$cmake = "$prefix\bin\cmake.exe"
$ninja = "$prefix\bin\ninja.exe"

# 1) 在 VsDevCmd 环境下用 Ninja 配置 + 构建
$cmd = 'call "D:\vs\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul && "' + $cmake + '" -S "' + $src + '" -B "' + $build + '" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="' + $prefix + '" && "' + $ninja + '" -C "' + $build + '"'
cmd /c $cmd

# 2) 运行前把 OCCT DLL 复制到 exe 旁（Windows 会优先从 exe 目录加载）
Copy-Item "$prefix\bin\TK*.dll" -Destination $build -Force
& "$build\ocaf_smoke.exe"
```

> 注意：conda 的 `occt` 是用较新的 `vc14_runtime` 构建的，若与本机 MSVC 运行时版本
> 不匹配会报 SxS 错误；本 fixture 已用静态 MSVC 运行时（`CMAKE_MSVC_RUNTIME_LIBRARY`）
> 规避 exe 自身的 CRT 清单依赖，运行仍需要 co-locate 的 OCCT DLL。
