

# SeekFlow 接入 SolidWorks 2025、UG/NX 18.0、ANSYS 18.1 的极详细实现文档

## 0. 项目目标

在 `WYZAAACCC/SeekFlow` 框架下增加一套本地工程软件工具，使 SeekFlow Agent 能够调用本机安装的：

```text
SolidWorks 2025
UG / Siemens NX 18.0
ANSYS 18.1
```

并完成真实工程任务，例如：

```text
SolidWorks:
- 新建零件
- 修改尺寸
- 导出 STEP / STL / PDF
- 批量打开与处理零件

UG / NX:
- 运行 NXOpen Journal
- 创建/修改零件
- 导入导出 STEP
- 批量处理 .prt 文件

ANSYS:
- 运行 APDL 命令流
- 批量求解
- 导出 .out / .rst / .txt 结果
- 解析关键结果指标
```

经过查看，SeekFlow 当前定位是一个 **DeepSeek-native zero-trust tool gateway**，重点是安全工具调用、沙箱、审计、权限策略和 Agent 执行，而不是直接操作桌面软件 UI。项目 README 说明它用于让 DeepSeek Agent 安全访问文件、网络、代码执行等能力，并通过 ToolPolicy、路径沙箱、风险等级、审计轨迹等机制控制工具调用。([GitHub][1])

因此本方案不建议让 Agent 直接“点鼠标操作软件”，而是通过本地桥接层调用工程软件官方接口。

---

# 1. 总体技术路线

## 1.1 推荐架构

```text
SeekFlow Agent
    │
    │ 调用注册好的工程工具
    ▼
seekflow_engineering_tools
    │
    ├── SolidWorks 2025 Bridge
    │       └── Python + COM / VBA Macro / C# COM
    │
    ├── UG / NX 18.0 Bridge
    │       └── NXOpen Python Journal / 文件队列桥接
    │
    └── ANSYS 18.1 Bridge
            └── APDL batch / Workbench Journal
```

也就是：

```text
Agent 不直接控制软件 UI
Agent 不直接运行任意危险脚本
Agent 只调用白名单工具函数
白名单工具函数再调用 SolidWorks / NX / ANSYS
```

SeekFlow 已支持工具注册、`@tool` 装饰器、`ToolDefinition`、`ToolPolicy`、风险等级、路径约束、权限检查等机制。`@tool` 会把 Python 函数转成 SeekFlow 可调用工具；`ToolPolicy` 可以声明 capabilities、risk、timeout、workspace_root、path_params 等字段。([GitHub][2]) ([GitHub][3])

## 1.2 为什么不推荐 Docker 直接跑 CAD/CAE

不要把 SolidWorks、UG/NX、ANSYS 18.1 直接放进 SeekFlow 的 Docker 沙箱里执行，原因如下：

```text
SolidWorks:
- 依赖 Windows 桌面程序
- COM 自动化依赖本机注册表和桌面会话
- Docker 内基本无法稳定调用 SolidWorks GUI/COM

UG / NX:
- NXOpen 通常需要在 NX 进程内部运行
- 许可证、环境变量、图形组件复杂
- 容器化成本高，不适合作为第一阶段

ANSYS 18.1:
- 可以批处理，但仍依赖本地安装路径和许可证
- APDL 命令流适合本机 subprocess 调用
```

SeekFlow 的 ContainerRunner、ProcessRunner、InProcessRunner 更适合普通脚本和受控工具，不适合直接封装商业 CAD/CAE 软件本体。SeekFlow README 里也将其执行层描述为 InProcessRunner、ProcessRunner、ContainerRunner 等 Runner，但工程软件本身仍应在本机原生环境中运行。([GitHub][1])

---

# 2. 版本适配结论

## 2.1 SolidWorks 2025

SolidWorks 2025 可以通过官方 API 做自动化。官方文档说明 SOLIDWORKS API 包含大量可从 VB、VBA、VB.NET、C++、C# 或宏文件调用的函数。([SOLIDWORKS Web Help][4])

推荐方式：

```text
第一优先：Python + pywin32 COM
第二优先：VBA Macro
第三优先：C# Add-in / C# COM 工具
```

适合任务：

```text
- 启动 SolidWorks
- 新建 Part / Assembly / Drawing
- 创建草图与特征
- 修改尺寸
- 保存 SLDPRT / SLDASM / SLDDRW
- 导出 STEP / STL / IGES / PDF
```

## 2.2 UG / NX 18.0

UG 现在通常指 Siemens NX。NX 自动化建议走 NXOpen Journal。已有 NXOpen Python 教程说明可以启用 Developer 选项卡，将 Journal Language 设为 Python，通过录制操作生成脚本，再改造成自动化脚本。([GitHub][5])

推荐方式：

```text
第一优先：NXOpen Python Journal
第二优先：NXOpen VB Journal
第三优先：外部进程 + NX 内部桥接 Journal
```

关键限制：

```text
NXOpen Python 一般要在 NX 进程内运行
不要默认把 NXOpen 脚本当普通 Python 脚本在系统终端执行
```

## 2.3 ANSYS 18.1

ANSYS 18.1 比较旧。当前 PyMAPDL / PyAnsys 生态更推荐较新的 ANSYS 版本，尤其 gRPC 推荐 ANSYS 2021 R1 及以上；官方 PyMAPDL 文档也说明 gRPC 是新版本推荐方式，老版本 console/CORBA 属于旧接口。([PyAnsys][6])

因此 ANSYS 18.1 推荐：

```text
第一优先：APDL 命令流 + batch 批处理
第二优先：Workbench Journal
第三优先：Mechanical ACT / 内置脚本
不建议第一阶段使用：新版 PyMechanical / PyFluent / PyAnsys 工作流
```

Workbench 也支持记录 Journal。Workbench Scripting Guide 说明可以通过 `File > Scripting > Record Journal` 录制脚本，并支持通过命令行参数 replay 脚本。([ANSYS Help][7])

---

# 3. 在 SeekFlow 中的实现方式选择

## 3.1 Phase 1：优先使用 SeekFlow 原生工具注册

建议第一阶段不要先做 MCP，而是直接做 SeekFlow native tools：

```python
from seekflow import tool
from seekflow.types import ToolPolicy
```

原因：

```text
1. 实现最直接
2. 可以立即使用 ToolPolicy 做路径、风险、超时控制
3. 方便写单元测试
4. 方便审计和错误处理
5. 不需要额外启动 MCP server
```

SeekFlow 的 Agent 支持 `add_tool()`、`add_tools()` 和默认工具加载。默认工具只有安全工具，危险能力需要显式开启。([GitHub][8])

## 3.2 Phase 2：再考虑 MCP

SeekFlow repo 里有 `mcp` 模块，Agent 也有 `add_mcp_server(name, command, args)`，会在 Agent 运行时启动 MCP server 并发现工具。([GitHub][8])

不过需要注意：当前 MCP 工具注册路径会把 MCP tool 包装成 `ToolDefinition`，并以 `server.tool` 形式命名；实现时要确认这些 MCP 工具是否附带了合适的 ToolPolicy，否则严格策略下可能被拒绝或过宽授权。MCP executor 会连接 server、发现工具、注册 wrapper。([GitHub][9])

SeekFlow README 的 roadmap 里也提到 v0.5 方向包括 MCP sandbox、tool freeze、mutation detection 等增强，说明 MCP 安全硬化仍是后续重点。([GitHub][1])

因此：

```text
第一阶段：SeekFlow native tools
第二阶段：把同一套桥接层再包装成 MCP server
```

---

# 4. 目标目录结构

建议在 SeekFlow 项目中新增一个独立包：

```text
SeekFlow/
├── src/
│   └── seekflow/
│       └── ...
│
├── integrations/
│   └── engineering_tools/
│       ├── pyproject.toml
│       ├── README.md
│       ├── examples/
│       │   ├── engineering_agent.py
│       │   ├── self_test.py
│       │   └── prompts/
│       │       ├── solidworks_box.md
│       │       ├── nx_block.md
│       │       └── ansys_beam.md
│       │
│       ├── src/
│       │   └── seekflow_engineering_tools/
│       │       ├── __init__.py
│       │       ├── config.py
│       │       ├── registry.py
│       │       │
│       │       ├── common/
│       │       │   ├── __init__.py
│       │       │   ├── models.py
│       │       │   ├── paths.py
│       │       │   ├── process.py
│       │       │   └── validation.py
│       │       │
│       │       ├── solidworks/
│       │       │   ├── __init__.py
│       │       │   ├── com_client.py
│       │       │   ├── tools.py
│       │       │   └── templates.py
│       │       │
│       │       ├── nx/
│       │       │   ├── __init__.py
│       │       │   ├── tools.py
│       │       │   ├── job_queue.py
│       │       │   ├── bridge_client.py
│       │       │   ├── nx_bridge_bootstrap.py
│       │       │   └── journal_templates.py
│       │       │
│       │       └── ansys/
│       │           ├── __init__.py
│       │           ├── tools.py
│       │           ├── apdl_runner.py
│       │           ├── apdl_templates.py
│       │           └── parsers.py
│       │
│       └── tests/
│           ├── test_paths.py
│           ├── test_ansys_runner_mock.py
│           ├── test_solidworks_mock.py
│           ├── test_nx_job_queue.py
│           └── test_registry.py
```

---

# 5. 配置文件设计

新增配置类：

```python
# integrations/engineering_tools/src/seekflow_engineering_tools/config.py

from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class EngineeringToolsConfig(BaseModel):
    workspace_root: Path = Field(...)

    # SolidWorks
    solidworks_enabled: bool = True
    solidworks_visible: bool = True
    solidworks_part_template: Path | None = None
    solidworks_default_timeout_s: int = 180

    # NX / UG
    nx_enabled: bool = True
    nx_job_root: Path | None = None
    nx_default_timeout_s: int = 300

    # ANSYS
    ansys_enabled: bool = True
    ansys181_exe: Path | None = None
    ansys_default_timeout_s: int = 600
    ansys_default_nproc: int = 2

    # Security
    allow_overwrite: bool = False
    max_input_file_mb: int = 200
    max_output_file_mb: int = 1000
```

支持环境变量：

```text
ENGINEERING_WORKSPACE=D:\seekflow_workspace

SOLIDWORKS_VISIBLE=1
SOLIDWORKS_PART_TEMPLATE=C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\Part.prtdot

NX_JOB_ROOT=D:\seekflow_workspace\nx_jobs

ANSYS181_EXE=C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe
ANSYS_DEFAULT_NPROC=4
```

所有输出文件必须限制在：

```text
ENGINEERING_WORKSPACE
```

不要允许 Agent 写入任意路径。

SeekFlow 的 PolicyEngine 本身支持 workspace_root、path_params、url_params、risk、capabilities 等检查；实现工具时应配合这些策略，不要绕过它。([GitHub][10])

---

# 6. 通用返回值设计

所有工程工具统一返回 JSON dict，不直接返回复杂对象。

```python
# common/models.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field


class EngineeringActionResult(BaseModel):
    ok: bool
    software: Literal["solidworks", "nx", "ansys"]
    action: str

    message: str = ""
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)

    log_path: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None

    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
```

返回示例：

```json
{
  "ok": true,
  "software": "ansys",
  "action": "run_apdl",
  "message": "ANSYS APDL job finished successfully.",
  "files_created": [
    "D:/seekflow_workspace/ansys_jobs/beam_001/beam_001.out",
    "D:/seekflow_workspace/ansys_jobs/beam_001/beam_001.rst"
  ],
  "metrics": {
    "max_displacement_mm": 0.42
  },
  "warnings": [],
  "error": null
}
```

---

# 7. 安全边界设计

## 7.1 工具不要设计成任意代码执行器

不要给 Agent 直接暴露这些危险工具：

```text
run_any_python(code: str)
run_any_vba(code: str)
run_any_powershell(command: str)
run_any_shell(command: str)
run_any_exe(path: str, args: list[str])
```

推荐暴露白名单工程动作：

```text
solidworks_create_box_part(...)
solidworks_export_step(...)
solidworks_modify_dimensions(...)

nx_create_block_part(...)
nx_export_step(...)
nx_run_whitelisted_journal(...)

ansys_run_apdl_template(...)
ansys_static_beam_rect(...)
ansys_parse_out_file(...)
```

如果确实需要 `ansys_run_apdl(input_text)`，也必须：

```text
1. 限制工作目录
2. 限制文件读写
3. 禁止 /SYS 等系统命令
4. 禁止路径跳出 workspace
5. 设置 timeout
6. 设置输出大小上限
7. 扫描 .out 中的 ERROR/WARNING
```

## 7.2 ToolPolicy 建议

SeekFlow 的 `ToolPolicy` 有 `capabilities`、`risk`、`timeout_s`、`workspace_root`、`path_params`、`requires_approval`、`runner` 等字段。([GitHub][3])

建议为工程工具定义如下权限：

```text
cad.solidworks.read
cad.solidworks.write
cad.nx.read
cad.nx.write
cae.ansys.read
cae.ansys.write
cae.ansys.solve
filesystem.read
filesystem.write
```

示例：

```python
from seekflow.types import ToolPolicy

solidworks_write_policy = ToolPolicy(
    capabilities={"cad.solidworks.write", "filesystem.write"},
    risk="write",
    timeout_s=180,
    workspace_root=workspace_root,
    path_params=frozenset({"out_sldprt", "out_step", "out_pdf"}),
    parallel_safe=False,
    requires_approval=False,
    idempotent=False,
)
```

如果工具可能覆盖文件或删除旧文件：

```python
ToolPolicy(
    capabilities={"cad.solidworks.write", "filesystem.write"},
    risk="destructive",
    requires_approval=True,
    ...
)
```

SeekFlow 的 PolicyEngine 会基于 risk、capabilities、workspace、approval 等进行授权；没有 policy 的工具在严格策略下会被拒绝。([GitHub][10])

---

# 8. SeekFlow Agent 侧接入方式

SeekFlow Agent 初始化时有 `dangerous_tools` 参数，内部会根据该参数设置最大风险等级；默认不开启危险工具时风险更低。([GitHub][8])

由于工程软件会写文件、启动外部程序、运行求解，建议创建一个专门的 EngineeringAgent helper。

```python
# registry.py

from __future__ import annotations

from pathlib import Path

from seekflow import DeepSeekAgent
from .config import EngineeringToolsConfig
from .solidworks.tools import build_solidworks_tools
from .nx.tools import build_nx_tools
from .ansys.tools import build_ansys_tools


ENGINEERING_CAPABILITIES = {
    "filesystem.read",
    "filesystem.write",
    "cad.solidworks.read",
    "cad.solidworks.write",
    "cad.nx.read",
    "cad.nx.write",
    "cae.ansys.read",
    "cae.ansys.write",
    "cae.ansys.solve",
}


def build_engineering_tools(config: EngineeringToolsConfig):
    tools = []

    if config.solidworks_enabled:
        tools.extend(build_solidworks_tools(config))

    if config.nx_enabled:
        tools.extend(build_nx_tools(config))

    if config.ansys_enabled:
        tools.extend(build_ansys_tools(config))

    return tools


def enable_engineering_tools(
    agent: DeepSeekAgent,
    config: EngineeringToolsConfig,
):
    """
    Attach engineering tools to a SeekFlow DeepSeekAgent.

    Note:
    SeekFlow currently exposes allow_filesystem/allow_network/allow_python style helpers.
    For custom capabilities, either:
    1. add a public allow_capabilities() method to SeekFlow upstream, or
    2. use a small subclass/helper that updates allowed capabilities consistently.
    """

    # Preferred implementation:
    # Add a public method to SeekFlow:
    # agent.allow_capabilities(ENGINEERING_CAPABILITIES, max_risk="write")
    #
    # If upstream does not yet have that method, implement EngineeringAgent subclass.
    agent._allowed_capabilities.update(ENGINEERING_CAPABILITIES)
    agent._max_risk = "write"
    agent._workspace_root = config.workspace_root

    agent.add_tools(build_engineering_tools(config))

    if hasattr(agent, "_invalidate_runtime"):
        agent._invalidate_runtime()

    return agent
```

更稳妥的做法是给 SeekFlow 提 PR 或在本集成包中创建子类：

```python
class EngineeringDeepSeekAgent(DeepSeekAgent):
    def allow_engineering(self, config: EngineeringToolsConfig):
        self._allowed_capabilities.update(ENGINEERING_CAPABILITIES)
        self._max_risk = "write"
        self._workspace_root = config.workspace_root
        self.add_tools(build_engineering_tools(config))
        self._invalidate_runtime()
        return self
```

原因：SeekFlow 当前已有 `allow_filesystem()`、`allow_network()`、`allow_python()` 这类 public helper，这些函数会注册工具并配置权限。([GitHub][8])
工程工具也应该遵循同样模式。

---

# 9. SolidWorks 2025 实现细节

## 9.1 依赖

仅 Windows 安装：

```toml
# integrations/engineering_tools/pyproject.toml

[project.optional-dependencies]
solidworks = [
    "pywin32>=306; platform_system == 'Windows'"
]
```

安装：

```bash
pip install -e .[solidworks]
```

## 9.2 SolidWorks COM Client

```python
# solidworks/com_client.py

from __future__ import annotations

from pathlib import Path
import time

try:
    import pythoncom
    import win32com.client as win32
except ImportError:
    pythoncom = None
    win32 = None


class SolidWorksNotAvailable(RuntimeError):
    pass


class SolidWorksClient:
    def __init__(
        self,
        visible: bool = True,
        part_template: Path | None = None,
    ):
        self.visible = visible
        self.part_template = Path(part_template) if part_template else None
        self.sw = None

    def connect(self):
        if win32 is None:
            raise SolidWorksNotAvailable(
                "pywin32 is not installed. Install with: pip install pywin32"
            )

        pythoncom.CoInitialize()

        try:
            self.sw = win32.Dispatch("SldWorks.Application")
        except Exception as exc:
            raise SolidWorksNotAvailable(
                "Failed to dispatch SldWorks.Application. "
                "Ensure SolidWorks 2025 is installed and registered."
            ) from exc

        self.sw.Visible = bool(self.visible)
        return self

    def health_check(self) -> dict:
        self.connect()
        return {
            "connected": True,
            "revision_number": str(self.sw.RevisionNumber()),
            "visible": bool(self.sw.Visible),
        }

    def new_part(self):
        if self.sw is None:
            self.connect()

        if not self.part_template:
            raise ValueError("solidworks_part_template is required for new_part().")

        model = self.sw.NewDocument(str(self.part_template), 0, 0, 0)
        if model is None:
            raise RuntimeError("SolidWorks NewDocument returned None.")

        return model

    def close(self):
        # Do not always quit SolidWorks.
        # The user may already have an active session.
        pass
```

## 9.3 SolidWorks 工具函数

```python
# solidworks/tools.py

from __future__ import annotations

from pathlib import Path
from seekflow import tool
from seekflow.types import ToolPolicy

from ..config import EngineeringToolsConfig
from ..common.models import EngineeringActionResult
from ..common.paths import ensure_inside_workspace
from .com_client import SolidWorksClient


def _solidworks_policy(config: EngineeringToolsConfig, path_params: set[str]):
    return ToolPolicy(
        capabilities={"cad.solidworks.write", "filesystem.write"},
        risk="write",
        timeout_s=config.solidworks_default_timeout_s,
        workspace_root=config.workspace_root,
        path_params=frozenset(path_params),
        parallel_safe=False,
        requires_approval=False,
        idempotent=False,
    )


def build_solidworks_tools(config: EngineeringToolsConfig):
    tools = []

    @tool(
        name="solidworks_health_check",
        description="Check whether local SolidWorks 2025 COM automation is available.",
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_health_check() -> dict:
        try:
            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            )
            info = client.health_check()
            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="health_check",
                message="SolidWorks COM is available.",
                metrics=info,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="health_check",
                error=str(exc),
            ).model_dump()

    solidworks_health_check = solidworks_health_check.with_policy(
        ToolPolicy(
            capabilities={"cad.solidworks.read"},
            risk="read",
            timeout_s=60,
            parallel_safe=False,
        )
    )

    @tool(
        name="solidworks_create_box_part",
        description=(
            "Create a rectangular block part in SolidWorks 2025 and optionally export STEP. "
            "All dimensions are in millimeters."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_create_box_part(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        out_sldprt: str,
        out_step: str | None = None,
    ) -> dict:
        out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)

        out_step_path = None
        if out_step:
            out_step_path = ensure_inside_workspace(config.workspace_root, out_step)

        try:
            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            ).connect()

            # Implementation note for Claude Code:
            # Use recorded SolidWorks 2025 macro as reference.
            # Create a sketch on Front Plane.
            # Draw center rectangle or corner rectangle.
            # Use meters internally because SolidWorks API length unit is commonly meters.
            # Extrude height_mm / 1000.0.
            # Save as SLDPRT.
            # Export STEP if requested.
            #
            # Exact FeatureExtrusion2 parameter list can be version-sensitive.
            # Use SolidWorks macro recorder to validate final COM calls.

            model = client.new_part()

            length_m = length_mm / 1000.0
            width_m = width_mm / 1000.0
            height_m = height_mm / 1000.0

            # Pseudocode placeholder:
            # model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, None, 0)
            # model.SketchManager.InsertSketch(True)
            # model.SketchManager.CreateCenterRectangle(0, 0, 0, length_m/2, width_m/2, 0)
            # model.SketchManager.InsertSketch(True)
            # model.FeatureManager.FeatureExtrusion2(... height_m ...)
            # model.SaveAs3(str(out_sldprt_path), 0, 2)
            #
            # For robust implementation:
            # 1. Add a macro-recorded helper.
            # 2. Write integration test on the actual machine.

            raise NotImplementedError(
                "Claude Code must replace this placeholder with SolidWorks 2025 COM calls "
                "validated from a recorded macro."
            )

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="create_box_part",
                error=str(exc),
            ).model_dump()

    solidworks_create_box_part = solidworks_create_box_part.with_policy(
        _solidworks_policy(config, {"out_sldprt", "out_step"})
    )

    tools.extend([
        solidworks_health_check,
        solidworks_create_box_part,
    ])

    return tools
```

## 9.4 SolidWorks 实现要求

Claude Code 实现时必须做这些事：

```text
1. 在 SolidWorks 2025 中手动录制一个“创建长方体零件并保存”的 VBA macro。
2. 把 macro 中的 API 调用翻译到 pywin32 COM。
3. 注意 SolidWorks API 长度单位通常按米传入，工具入参统一用 mm。
4. 保存文件前检查路径是否在 workspace 内。
5. 如果输出文件已存在：
   - allow_overwrite=False 时直接失败
   - allow_overwrite=True 时覆盖，但该工具 risk 应设为 destructive 或 requires_approval=True
6. 所有异常都转换为 EngineeringActionResult，不要把 COM traceback 直接丢给 Agent。
```

## 9.5 SolidWorks 第一阶段工具清单

```text
solidworks_health_check()
solidworks_create_box_part(length_mm, width_mm, height_mm, out_sldprt, out_step?)
solidworks_open_part(file_path)
solidworks_export_step(input_sldprt, out_step)
solidworks_export_stl(input_sldprt, out_stl)
solidworks_modify_global_variables(input_sldprt, variables, out_sldprt?)
solidworks_create_drawing_pdf(input_sldprt, drawing_template, out_pdf)
```

---

# 10. UG / NX 18.0 实现细节

## 10.1 NX 的核心限制

NXOpen Python 通常依赖 NX 当前会话。不要默认从系统 Python 里直接：

```bash
python create_part.py
```

因为这样大概率找不到 NXOpen 模块，也没有 NX Session。

推荐做一个 **文件队列式 NX Bridge**：

```text
SeekFlow Tool
    │
    │ 写入 job JSON
    ▼
D:\seekflow_workspace\nx_jobs\pending\job_001.json
    │
    │ NX 内部长期运行 nx_bridge_bootstrap.py
    ▼
NXOpen 执行 job
    │
    ▼
D:\seekflow_workspace\nx_jobs\done\job_001.result.json
```

也就是：

```text
用户先打开 NX 18.0
在 NX 中运行一次 nx_bridge_bootstrap.py
之后 Agent 通过 job queue 派发任务
```

这是第一阶段最稳的方式。

## 10.2 NX Job 格式

```json
{
  "job_id": "20260525_001",
  "action": "create_block_part",
  "params": {
    "length_mm": 100,
    "width_mm": 60,
    "height_mm": 30,
    "out_prt": "D:/seekflow_workspace/nx_out/block_001.prt",
    "out_step": "D:/seekflow_workspace/nx_out/block_001.step"
  }
}
```

结果：

```json
{
  "job_id": "20260525_001",
  "ok": true,
  "message": "NX job finished.",
  "files_created": [
    "D:/seekflow_workspace/nx_out/block_001.prt",
    "D:/seekflow_workspace/nx_out/block_001.step"
  ],
  "metrics": {},
  "error": null
}
```

## 10.3 NX job queue client

```python
# nx/job_queue.py

from __future__ import annotations

from pathlib import Path
import json
import time
import uuid


class NXJobQueue:
    def __init__(self, job_root: Path):
        self.job_root = Path(job_root)
        self.pending_dir = self.job_root / "pending"
        self.running_dir = self.job_root / "running"
        self.done_dir = self.job_root / "done"
        self.failed_dir = self.job_root / "failed"

        for d in [
            self.pending_dir,
            self.running_dir,
            self.done_dir,
            self.failed_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def submit(self, action: str, params: dict) -> str:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "action": action,
            "params": params,
            "created_at": time.time(),
        }
        job_path = self.pending_dir / f"{job_id}.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job_id

    def wait(self, job_id: str, timeout_s: int) -> dict:
        done_path = self.done_dir / f"{job_id}.result.json"
        failed_path = self.failed_dir / f"{job_id}.result.json"

        deadline = time.time() + timeout_s

        while time.time() < deadline:
            if done_path.exists():
                return json.loads(done_path.read_text(encoding="utf-8"))

            if failed_path.exists():
                return json.loads(failed_path.read_text(encoding="utf-8"))

            time.sleep(1.0)

        raise TimeoutError(f"NX job {job_id} timed out after {timeout_s} seconds.")
```

## 10.4 NX 内部 bootstrap journal

文件：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py
```

该文件需要在 NX 18.0 内通过 Journal 运行。

示意代码：

```python
# nx_bridge_bootstrap.py
# This file is intended to run inside Siemens NX / UG as an NXOpen Python Journal.

import NXOpen
import os
import json
import time
import traceback
import shutil


JOB_ROOT = os.environ.get("NX_JOB_ROOT", r"D:\seekflow_workspace\nx_jobs")
PENDING = os.path.join(JOB_ROOT, "pending")
RUNNING = os.path.join(JOB_ROOT, "running")
DONE = os.path.join(JOB_ROOT, "done")
FAILED = os.path.join(JOB_ROOT, "failed")


def ensure_dirs():
    for d in [PENDING, RUNNING, DONE, FAILED]:
        os.makedirs(d, exist_ok=True)


def write_result(directory, job_id, result):
    out_path = os.path.join(directory, f"{job_id}.result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def create_block_part(session, params):
    """
    Implement with NXOpen APIs validated in NX 18.0.
    Claude Code should use a recorded NXOpen Python Journal as reference.
    """

    length_mm = float(params["length_mm"])
    width_mm = float(params["width_mm"])
    height_mm = float(params["height_mm"])
    out_prt = params["out_prt"]
    out_step = params.get("out_step")

    # Pseudocode:
    # 1. session.Parts.NewDisplay(...)
    # 2. Create sketch or block feature
    # 3. Save .prt
    # 4. Export STEP if out_step is given
    #
    # Exact API calls should be generated from NX 18.0 journal recording.

    raise NotImplementedError(
        "Replace with NXOpen 18.0 journal-recorded implementation."
    )


def export_step(session, params):
    input_prt = params["input_prt"]
    out_step = params["out_step"]

    # Pseudocode:
    # Open part
    # Use STEP214Creator / DexManager exporter depending on NX 18.0 API
    # Commit export

    raise NotImplementedError(
        "Replace with NXOpen 18.0 STEP export implementation."
    )


ACTION_HANDLERS = {
    "create_block_part": create_block_part,
    "export_step": export_step,
}


def process_one_job(session, job_file):
    basename = os.path.basename(job_file)
    running_file = os.path.join(RUNNING, basename)

    shutil.move(job_file, running_file)

    with open(running_file, "r", encoding="utf-8") as f:
        job = json.load(f)

    job_id = job["job_id"]
    action = job["action"]
    params = job.get("params", {})

    try:
        if action not in ACTION_HANDLERS:
            raise ValueError(f"Unknown NX action: {action}")

        result_payload = ACTION_HANDLERS[action](session, params)

        result = {
            "job_id": job_id,
            "ok": True,
            "message": "NX job finished.",
            "files_created": result_payload.get("files_created", []),
            "metrics": result_payload.get("metrics", {}),
            "error": None,
        }
        write_result(DONE, job_id, result)

    except Exception as exc:
        result = {
            "job_id": job_id,
            "ok": False,
            "message": "NX job failed.",
            "files_created": [],
            "metrics": {},
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_result(FAILED, job_id, result)

    finally:
        try:
            os.remove(running_file)
        except OSError:
            pass


def main():
    ensure_dirs()

    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    lw.WriteLine("SeekFlow NX Bridge started.")
    lw.WriteLine("Watching: " + JOB_ROOT)

    # Simple long-running loop.
    # For production, add a stop file such as JOB_ROOT/STOP.
    while True:
        stop_file = os.path.join(JOB_ROOT, "STOP")
        if os.path.exists(stop_file):
            lw.WriteLine("SeekFlow NX Bridge stopped by STOP file.")
            break

        jobs = [
            os.path.join(PENDING, f)
            for f in os.listdir(PENDING)
            if f.endswith(".json")
        ]

        for job_file in jobs:
            lw.WriteLine("Processing NX job: " + job_file)
            process_one_job(session, job_file)

        time.sleep(1.0)


if __name__ == "__main__":
    main()
```

## 10.5 SeekFlow NX 工具

```python
# nx/tools.py

from __future__ import annotations

from seekflow import tool
from seekflow.types import ToolPolicy

from ..config import EngineeringToolsConfig
from ..common.models import EngineeringActionResult
from ..common.paths import ensure_inside_workspace
from .job_queue import NXJobQueue


def build_nx_tools(config: EngineeringToolsConfig):
    tools = []
    job_root = config.nx_job_root or (config.workspace_root / "nx_jobs")

    @tool(
        name="nx_health_check",
        description=(
            "Check whether the NX job queue directory exists. "
            "This does not guarantee that NX bridge journal is currently running."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_health_check() -> dict:
        try:
            q = NXJobQueue(job_root)
            return EngineeringActionResult(
                ok=True,
                software="nx",
                action="health_check",
                message=(
                    "NX job queue is available. "
                    "Ensure nx_bridge_bootstrap.py is running inside NX 18.0."
                ),
                metrics={"job_root": str(job_root)},
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="health_check",
                error=str(exc),
            ).model_dump()

    nx_health_check = nx_health_check.with_policy(
        ToolPolicy(
            capabilities={"cad.nx.read", "filesystem.read"},
            risk="read",
            timeout_s=30,
            workspace_root=config.workspace_root,
            parallel_safe=True,
        )
    )

    @tool(
        name="nx_create_block_part",
        description=(
            "Submit a job to NX 18.0 bridge to create a block part. "
            "Requires nx_bridge_bootstrap.py running inside NX."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_create_block_part(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        out_prt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            out_prt_path = ensure_inside_workspace(config.workspace_root, out_prt)
            params = {
                "length_mm": length_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "out_prt": str(out_prt_path),
            }

            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
                params["out_step"] = str(out_step_path)

            q = NXJobQueue(job_root)
            job_id = q.submit("create_block_part", params)
            result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)

            return EngineeringActionResult(
                ok=bool(result.get("ok")),
                software="nx",
                action="create_block_part",
                message=result.get("message", ""),
                files_created=result.get("files_created", []),
                metrics=result.get("metrics", {}),
                error=result.get("error"),
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_block_part",
                error=str(exc),
            ).model_dump()

    nx_create_block_part = nx_create_block_part.with_policy(
        ToolPolicy(
            capabilities={"cad.nx.write", "filesystem.write"},
            risk="write",
            timeout_s=config.nx_default_timeout_s + 10,
            workspace_root=config.workspace_root,
            path_params=frozenset({"out_prt", "out_step"}),
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        nx_health_check,
        nx_create_block_part,
    ])

    return tools
```

## 10.6 NX 第一阶段工具清单

```text
nx_health_check()
nx_create_block_part(length_mm, width_mm, height_mm, out_prt, out_step?)
nx_export_step(input_prt, out_step)
nx_run_whitelisted_journal(action, params)
```

不要第一阶段暴露：

```text
nx_run_arbitrary_python_journal(code: str)
```

因为这等于给 Agent 在 NX 内部任意执行代码。

---

# 11. ANSYS 18.1 实现细节

## 11.1 推荐方式

ANSYS 18.1 优先走 APDL batch：

```text
Codex / Agent
    ↓
SeekFlow ansys_static_beam_rect(...)
    ↓
生成 .inp APDL 文件
    ↓
subprocess 调用 ansys181.exe -b -i input.inp -o output.out
    ↓
解析 output.out / result.txt
```

原因：

```text
1. ANSYS 18.1 老版本，APDL 稳定
2. APDL 是纯文本，适合 Agent 生成和修改
3. batch 模式容易审计
4. 不依赖新版 PyAnsys/gRPC
```

## 11.2 APDL runner

```python
# ansys/apdl_runner.py

from __future__ import annotations

from pathlib import Path
import subprocess
import time


class AnsysAPDLRunner:
    def __init__(
        self,
        ansys_exe: Path,
        workspace_root: Path,
        default_timeout_s: int = 600,
        default_nproc: int = 2,
    ):
        self.ansys_exe = Path(ansys_exe)
        self.workspace_root = Path(workspace_root)
        self.default_timeout_s = default_timeout_s
        self.default_nproc = default_nproc

    def health_check(self) -> dict:
        return {
            "ansys_exe": str(self.ansys_exe),
            "exists": self.ansys_exe.exists(),
        }

    def run_apdl_file(
        self,
        input_file: Path,
        job_dir: Path,
        jobname: str,
        timeout_s: int | None = None,
        nproc: int | None = None,
    ) -> dict:
        input_file = Path(input_file)
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        output_file = job_dir / f"{jobname}.out"

        if not self.ansys_exe.exists():
            raise FileNotFoundError(f"ANSYS executable not found: {self.ansys_exe}")

        timeout_s = timeout_s or self.default_timeout_s
        nproc = nproc or self.default_nproc

        # The exact ANSYS 18.1 command-line flags may vary by installation.
        # Validate on target machine. Common Mechanical APDL batch shape:
        cmd = [
            str(self.ansys_exe),
            "-b",
            "-i", str(input_file),
            "-o", str(output_file),
            "-j", jobname,
        ]

        # Optional:
        # cmd.extend(["-np", str(nproc)])

        started = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(job_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed_s = time.time() - started

        stdout_tail = proc.stdout[-4000:] if proc.stdout else ""
        stderr_tail = proc.stderr[-4000:] if proc.stderr else ""

        out_text = ""
        if output_file.exists():
            out_text = output_file.read_text(errors="ignore")[-8000:]

        has_error = (
            proc.returncode != 0
            or "*** ERROR ***" in out_text
            or "ERROR" in stderr_tail.upper()
        )

        has_warning = "*** WARNING ***" in out_text

        return {
            "returncode": proc.returncode,
            "elapsed_s": elapsed_s,
            "output_file": str(output_file),
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "out_tail": out_text,
            "has_error": has_error,
            "has_warning": has_warning,
        }
```

## 11.3 APDL 模板

```python
# ansys/apdl_templates.py

def static_cantilever_beam_rect_apdl(
    length_mm: float,
    width_mm: float,
    height_mm: float,
    force_n: float,
    young_mpa: float = 210000.0,
    poisson: float = 0.3,
    element_size_mm: float = 10.0,
) -> str:
    return f"""
/CLEAR
/FILNAME,beam_job
/PREP7

! Units: N, mm, MPa

ET,1,SOLID185
MP,EX,1,{young_mpa}
MP,PRXY,1,{poisson}

BLOCK,0,{length_mm},0,{width_mm},0,{height_mm}

ESIZE,{element_size_mm}
VMESH,ALL

/SOLU
ANTYPE,STATIC

! Fix x=0 face
NSEL,S,LOC,X,0
D,ALL,ALL,0

! Apply force on x=L face in negative Z direction
NSEL,S,LOC,X,{length_mm}
*GET,NCOUNT,NODE,0,COUNT
F,ALL,FZ,{-abs(force_n)}/NCOUNT

ALLSEL,ALL
SOLVE
FINISH

/POST1
SET,LAST

! Get maximum displacement magnitude
NSORT,U,SUM
*GET,MAXU,SORT,0,MAX

! Get maximum equivalent stress if available
! For SOLID185, equivalent stress can be listed via PRNSOL/S.
PRNSOL,U
PRNSOL,S,EQV

/OUTPUT,result_summary,txt
*VWRITE,MAXU
('MAX_DISPLACEMENT_MM=',E16.8)
/OUTPUT

FINISH
"""
```

## 11.4 ANSYS 工具函数

```python
# ansys/tools.py

from __future__ import annotations

from pathlib import Path
import time

from seekflow import tool
from seekflow.types import ToolPolicy

from ..config import EngineeringToolsConfig
from ..common.models import EngineeringActionResult
from ..common.paths import ensure_inside_workspace
from .apdl_runner import AnsysAPDLRunner
from .apdl_templates import static_cantilever_beam_rect_apdl
from .parsers import parse_result_summary


def build_ansys_tools(config: EngineeringToolsConfig):
    tools = []

    @tool(
        name="ansys_health_check",
        description="Check whether ANSYS 18.1 Mechanical APDL executable is configured.",
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_health_check() -> dict:
        try:
            if config.ansys181_exe is None:
                raise ValueError("ansys181_exe is not configured.")

            runner = AnsysAPDLRunner(
                ansys_exe=config.ansys181_exe,
                workspace_root=config.workspace_root,
                default_timeout_s=config.ansys_default_timeout_s,
                default_nproc=config.ansys_default_nproc,
            )
            info = runner.health_check()
            return EngineeringActionResult(
                ok=bool(info["exists"]),
                software="ansys",
                action="health_check",
                message="ANSYS executable check finished.",
                metrics=info,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="health_check",
                error=str(exc),
            ).model_dump()

    ansys_health_check = ansys_health_check.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    @tool(
        name="ansys_static_cantilever_beam_rect",
        description=(
            "Run a simple ANSYS 18.1 APDL static analysis for a rectangular cantilever beam. "
            "Units: mm, N, MPa."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_static_cantilever_beam_rect(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        force_n: float,
        jobname: str,
        element_size_mm: float = 10.0,
    ) -> dict:
        try:
            if config.ansys181_exe is None:
                raise ValueError("ansys181_exe is not configured.")

            safe_jobname = "".join(
                ch for ch in jobname if ch.isalnum() or ch in ("_", "-")
            )[:64]
            if not safe_jobname:
                safe_jobname = f"ansys_job_{int(time.time())}"

            job_dir = ensure_inside_workspace(
                config.workspace_root,
                f"ansys_jobs/{safe_jobname}",
            )
            job_dir.mkdir(parents=True, exist_ok=True)

            inp_path = job_dir / f"{safe_jobname}.inp"
            apdl = static_cantilever_beam_rect_apdl(
                length_mm=length_mm,
                width_mm=width_mm,
                height_mm=height_mm,
                force_n=force_n,
                element_size_mm=element_size_mm,
            )
            inp_path.write_text(apdl, encoding="utf-8")

            runner = AnsysAPDLRunner(
                ansys_exe=config.ansys181_exe,
                workspace_root=config.workspace_root,
                default_timeout_s=config.ansys_default_timeout_s,
                default_nproc=config.ansys_default_nproc,
            )
            run = runner.run_apdl_file(
                input_file=inp_path,
                job_dir=job_dir,
                jobname=safe_jobname,
                timeout_s=config.ansys_default_timeout_s,
            )

            summary_path = job_dir / "result_summary.txt"
            metrics = {}
            if summary_path.exists():
                metrics = parse_result_summary(summary_path)

            warnings = []
            if run["has_warning"]:
                warnings.append("ANSYS output contains warning messages.")

            return EngineeringActionResult(
                ok=not run["has_error"],
                software="ansys",
                action="static_cantilever_beam_rect",
                message="ANSYS APDL batch job finished.",
                files_created=[
                    str(inp_path),
                    run["output_file"],
                    str(summary_path) if summary_path.exists() else "",
                ],
                log_path=run["output_file"],
                stdout_tail=run["stdout_tail"],
                stderr_tail=run["stderr_tail"],
                metrics=metrics,
                warnings=warnings,
                error=None if not run["has_error"] else "ANSYS reported an error.",
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="static_cantilever_beam_rect",
                error=str(exc),
            ).model_dump()

    ansys_static_cantilever_beam_rect = ansys_static_cantilever_beam_rect.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.write", "cae.ansys.solve", "filesystem.write"},
            risk="write",
            timeout_s=config.ansys_default_timeout_s + 30,
            workspace_root=config.workspace_root,
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        ansys_health_check,
        ansys_static_cantilever_beam_rect,
    ])

    return tools
```

## 11.5 ANSYS 第一阶段工具清单

```text
ansys_health_check()
ansys_static_cantilever_beam_rect(...)
ansys_run_apdl_template(template_name, parameters, jobname)
ansys_parse_result_summary(result_file)
```

第二阶段再加：

```text
ansys_run_workbench_journal(journal_path, project_path)
ansys_update_workbench_project(project_path)
ansys_export_workbench_results(project_path, out_dir)
```

---

# 12. 通用路径安全工具

```python
# common/paths.py

from __future__ import annotations

from pathlib import Path


def ensure_inside_workspace(workspace_root: Path, user_path: str | Path) -> Path:
    workspace_root = Path(workspace_root).resolve()
    candidate = Path(user_path)

    if not candidate.is_absolute():
        candidate = workspace_root / candidate

    candidate = candidate.resolve()

    try:
        candidate.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Path is outside workspace. path={candidate}, workspace={workspace_root}"
        )

    return candidate


def ensure_extension(path: Path, allowed: set[str]) -> Path:
    if path.suffix.lower() not in allowed:
        raise ValueError(
            f"File extension {path.suffix!r} is not allowed. Allowed: {sorted(allowed)}"
        )
    return path
```

虽然 SeekFlow 的 PolicyEngine 已支持 workspace/path 检查，但工具内部仍要二次校验，形成双保险。

---

# 13. 示例 Agent

```python
# examples/engineering_agent.py

from pathlib import Path

from seekflow import DeepSeekAgent

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import enable_engineering_tools


def main():
    workspace = Path(r"D:\seekflow_workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    config = EngineeringToolsConfig(
        workspace_root=workspace,
        solidworks_enabled=True,
        solidworks_visible=True,
        solidworks_part_template=Path(
            r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\Part.prtdot"
        ),
        nx_enabled=True,
        nx_job_root=workspace / "nx_jobs",
        ansys_enabled=True,
        ansys181_exe=Path(
            r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"
        ),
        ansys_default_timeout_s=600,
    )

    agent = DeepSeekAgent(
        role="Engineering automation agent",
        goal=(
            "Create CAD models and run CAE analyses through local approved tools only. "
            "Never invent file results. Always report tool output."
        ),
        backstory=(
            "You are connected to local SolidWorks 2025, NX 18.0, and ANSYS 18.1 "
            "through audited SeekFlow tools."
        ),
        dangerous_tools=True,
        max_steps=8,
    )

    enable_engineering_tools(agent, config)

    result = agent.run(
        "请检查 SolidWorks、NX、ANSYS 是否可用。"
    )
    print(result)


if __name__ == "__main__":
    main()
```

---

# 14. Claude Code 实施阶段划分

## Phase A：确认 SeekFlow 基线可运行

Claude Code 需要先做：

```bash
git clone https://github.com/WYZAAACCC/SeekFlow
cd SeekFlow
pip install -e .
python -c "import seekflow; print(seekflow)"
```

确认：

```text
1. Python >= 3.10
2. seekflow.DeepSeekAgent 可 import
3. seekflow.tool 可 import
4. ToolPolicy 可 import
5. 本地测试能运行
```

SeekFlow 的 `pyproject.toml` 声明 Python 需要 >=3.10，并依赖 openai、pydantic、jsonschema、httpx 等，另有 MCP optional dependency。([GitHub][11])

## Phase B：增加 engineering_tools 集成包

实现：

```text
integrations/engineering_tools/
```

并确保：

```bash
pip install -e integrations/engineering_tools
```

可正常安装。

## Phase C：先写 mock 测试

必须先写不依赖真实软件的单元测试：

```text
test_paths.py:
- 禁止 .. 跳出 workspace
- 禁止绝对路径跳出 workspace
- 允许 workspace 内路径

test_ansys_runner_mock.py:
- mock subprocess.run
- 模拟 returncode=0
- 模拟 out 文件存在
- 模拟 "*** ERROR ***" 检测

test_nx_job_queue.py:
- submit 后 pending 里有 json
- wait 能读取 done result
- timeout 正常触发

test_registry.py:
- build_engineering_tools 返回工具
- 每个工具都有 policy
```

## Phase D：实现 ANSYS 18.1

优先实现 ANSYS，因为最容易验证：

```text
1. ansys_health_check
2. ansys_static_cantilever_beam_rect
3. APDL 生成
4. batch 调用
5. out 文件解析
```

验收：

```bash
python integrations/engineering_tools/examples/self_test.py --ansys
```

成功条件：

```text
1. 能找到 ansys181.exe
2. 生成 .inp
3. 生成 .out
4. 没有 "*** ERROR ***"
5. result_summary.txt 中能解析 MAX_DISPLACEMENT_MM
```

## Phase E：实现 SolidWorks 2025

步骤：

```text
1. 在目标机器安装 pywin32
2. 确认 SolidWorks 2025 可手动启动
3. 运行 solidworks_health_check
4. 在 SolidWorks 中录制创建长方体 macro
5. 把 macro 转成 pywin32 COM
6. 实现 solidworks_create_box_part
7. 实现 solidworks_export_step
```

验收：

```text
1. SolidWorks 被启动或连接
2. workspace 中生成 .sldprt
3. workspace 中生成 .step
4. 文件大小 > 0
5. SolidWorks 不崩溃
6. 多次运行不会污染非 workspace 路径
```

## Phase F：实现 NX 18.0

步骤：

```text
1. 在 workspace 创建 nx_jobs/pending、running、done、failed
2. 在 NX 18.0 中运行 nx_bridge_bootstrap.py
3. Agent 工具写入 pending job
4. NX bridge 处理 job
5. SeekFlow 工具轮询 done/failed result
```

验收：

```text
1. nx_health_check 能创建 job queue
2. NX ListingWindow 显示 SeekFlow NX Bridge started
3. nx_create_block_part 写入 job
4. NX 生成 .prt
5. NX 导出 .step
6. SeekFlow 收到 ok=true
```

## Phase G：Agent 真实调用测试

测试 Prompt：

```text
请调用本地工程工具完成以下任务：
1. 检查 SolidWorks、NX、ANSYS 是否可用；
2. 用 SolidWorks 创建一个 100mm × 60mm × 30mm 的长方体零件，保存为 sw_box.sldprt，并导出 sw_box.step；
3. 用 NX 创建一个 80mm × 40mm × 20mm 的长方体零件，保存为 nx_block.prt，并导出 nx_block.step；
4. 用 ANSYS 18.1 计算一个 200mm × 20mm × 20mm 的悬臂梁，端部受力 1000N，输出最大位移。
请最后列出生成的文件路径和结果。
```

成功标准：

```text
1. Agent 不编造结果
2. Agent 必须实际调用工具
3. 所有文件在 workspace 内
4. ANSYS 结果来自 output/result_summary
5. 失败时清楚说明是哪一个软件失败
```

---

# 15. 可交付给 Claude Code 的任务说明

下面这段可以直接复制给 Claude Code：

```text
你正在修改 GitHub 项目 WYZAAACCC/SeekFlow。目标是在 SeekFlow 下实现一个本地 engineering_tools 集成包，使 SeekFlow Agent 能调用本机安装的 SolidWorks 2025、UG/NX 18.0 和 ANSYS 18.1 进行真实工作。

请严格按以下要求实现：

一、总体原则
1. 不要让 Agent 直接操作 GUI。
2. 不要把 SolidWorks、NX、ANSYS 放进 Docker。
3. 不要暴露任意 shell/python/vba/apdl 执行器给 Agent。
4. 使用 SeekFlow 的 @tool 和 ToolPolicy 注册白名单工程工具。
5. 所有文件读写必须限制在 ENGINEERING_WORKSPACE 内。
6. 所有工具返回统一 JSON 结构 EngineeringActionResult。
7. 所有失败必须返回结构化错误，不要让程序直接崩溃。
8. 每个工具必须有 timeout、risk、capabilities、workspace_root、path_params 等策略。
9. 先做 mock 测试，再做真实软件集成。

二、目录结构
在 integrations/engineering_tools 下创建独立 Python 包，包含：
- config.py
- registry.py
- common/models.py
- common/paths.py
- solidworks/com_client.py
- solidworks/tools.py
- nx/job_queue.py
- nx/tools.py
- nx/nx_bridge_bootstrap.py
- ansys/apdl_runner.py
- ansys/apdl_templates.py
- ansys/parsers.py
- ansys/tools.py
- examples/engineering_agent.py
- tests/

三、SolidWorks 2025
1. 使用 pywin32 COM 调用 SldWorks.Application。
2. 实现 solidworks_health_check。
3. 实现 solidworks_create_box_part(length_mm, width_mm, height_mm, out_sldprt, out_step?)。
4. 实现 solidworks_export_step(input_sldprt, out_step)。
5. 长度入参统一 mm，COM 内部按 SolidWorks API 需要转换。
6. 用 SolidWorks 2025 宏录制功能验证最终 API 调用。
7. 输出必须在 workspace 内。

四、UG/NX 18.0
1. 不要假设 NXOpen 可以在系统 Python 中直接 import。
2. 实现文件队列式 NX bridge：
   - SeekFlow 工具写 jobs/pending/*.json
   - NX 内部运行 nx_bridge_bootstrap.py
   - bootstrap 读取 job，调用 NXOpen，写 done/failed result
3. 实现 nx_health_check。
4. 实现 nx_create_block_part(length_mm, width_mm, height_mm, out_prt, out_step?)。
5. 实现 nx_export_step(input_prt, out_step)。
6. NXOpen 具体建模 API 要通过 NX 18.0 Journal Recorder 录制后改造。
7. 不暴露任意 NXOpen Python 执行器。

五、ANSYS 18.1
1. 第一阶段不要使用新版 PyAnsys/PyMechanical。
2. 使用 APDL batch 调用 ansys181.exe。
3. 实现 ansys_health_check。
4. 实现 ansys_static_cantilever_beam_rect(length_mm, width_mm, height_mm, force_n, jobname, element_size_mm)。
5. 自动生成 .inp，调用 ansys181.exe -b -i input.inp -o output.out -j jobname。
6. 解析 output.out 中的 ERROR/WARNING。
7. 输出 result_summary.txt，并解析 MAX_DISPLACEMENT_MM。
8. 所有 job 目录必须在 workspace/ansys_jobs 下。

六、SeekFlow 集成
1. 实现 build_engineering_tools(config)。
2. 实现 enable_engineering_tools(agent, config) 或 EngineeringDeepSeekAgent.allow_engineering(config)。
3. 给 Agent 增加以下 capabilities：
   - filesystem.read
   - filesystem.write
   - cad.solidworks.read
   - cad.solidworks.write
   - cad.nx.read
   - cad.nx.write
   - cae.ansys.read
   - cae.ansys.write
   - cae.ansys.solve
4. 如果 SeekFlow 没有 public allow_capabilities 方法，可以先用 EngineeringDeepSeekAgent 子类封装，不要在业务代码到处直接改 private attrs。

七、验收测试
1. pytest mock 测试全部通过。
2. ansys_health_check 能找到 ANSYS 18.1。
3. ansys_static_cantilever_beam_rect 能生成 .inp、.out、result_summary.txt。
4. solidworks_health_check 能连接 SolidWorks 2025。
5. solidworks_create_box_part 能生成 .sldprt 和 .step。
6. nx_health_check 能创建 job queue。
7. 在 NX 18.0 中运行 nx_bridge_bootstrap.py 后，nx_create_block_part 能生成 .prt 和 .step。
8. 所有输出都在 ENGINEERING_WORKSPACE 内。
9. Agent 最终回答必须基于工具返回，不得编造文件或结果。
```

---

# 16. 最终推荐落地顺序

建议不要三套软件同时硬上，按这个顺序实现：

```text
第 1 步：ANSYS 18.1 APDL batch
原因：最容易自动化，最容易验证

第 2 步：SolidWorks 2025 COM
原因：COM 稳定，但需要真实桌面环境

第 3 步：NX 18.0 文件队列 bridge
原因：NXOpen 环境最特殊，需要在 NX 内部跑 bootstrap

第 4 步：统一注册到 SeekFlow Agent

第 5 步：可选封装 MCP server
```

最终形态应该是：

```text
SeekFlow Agent
    ↓
受控工程工具
    ↓
SolidWorks COM / NXOpen Bridge / ANSYS APDL Batch
    ↓
真实本地工程软件
    ↓
生成 CAD 文件、仿真结果、日志
    ↓
Agent 读取结构化结果并汇报
```

这套方案的关键不是“让 Agent 自由写脚本乱跑”，而是把 SolidWorks、NX、ANSYS 的能力拆成一组安全、可审计、可测试的工程工具，然后交给 SeekFlow 的 ToolPolicy 去管控。

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/decorator.py "SeekFlow/src/seekflow/tools/decorator.py at main · WYZAAACCC/SeekFlow · GitHub"
[3]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/types.py "SeekFlow/src/seekflow/types.py at main · WYZAAACCC/SeekFlow · GitHub"
[4]: https://help.solidworks.com/2025/english/solidworks/sldworks/c_solidworks_api.htm?utm_source=chatgpt.com "SOLIDWORKS API - 2025"
[5]: https://github.com/Foadsf/NXOpen_Python_tutorials?utm_source=chatgpt.com "a collection of NXOpen Python tutorials ..."
[6]: https://mapdl.docs.pyansys.com/version/stable/api/_autosummary/ansys.mapdl.core.launcher.launch_mapdl.html?utm_source=chatgpt.com "launch_mapdl - PyMAPDL"
[7]: https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/pdf/Workbench_Scripting_Guide.pdf?utm_source=chatgpt.com "Workbench Scripting Guide"
[8]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/agent/agent.py "SeekFlow/src/seekflow/agent/agent.py at main · WYZAAACCC/SeekFlow · GitHub"
[9]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/mcp/executor.py "SeekFlow/src/seekflow/mcp/executor.py at main · WYZAAACCC/SeekFlow · GitHub"
[10]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/policy.py "SeekFlow/src/seekflow/policy.py at main · WYZAAACCC/SeekFlow · GitHub"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
