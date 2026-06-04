# v6.2 Stress30 审计报告

**日期**: 2026-06-04
**测试**: 30 个全新高复杂度工业零件 (不与之前 35 个重合)
**代码基线**: v6.2 (GeometricParameterSolver + PathAnalysis + BSpline sweep + repair_hints)

---

## 一、总体结果

| 指标 | 数值 |
|------|------|
| 总零件数 | 30 |
| STEP 生成 | **25/30 (83%)** |
| 几何异常 | 2 (g22 MULTI_SOLID, g26 负体积) |
| 完全失败 | 5 |
| 平均 LLM 调用 | 1.3 次/case |
| 平均耗时 | 22s/case |

## 二、5 个失败 Case 根因分析

| # | Case | 失败类型 | 根因 | 可修复? |
|---|------|---------|------|---------|
| 1 | g8_var_duct | BUILD_FAIL | loft_sections 在 4 截面变径 (圆→矩形→圆) 时 OCCT 构建失败 | ⚠️ 需增强 loft handler |
| 2 | g14_vacuum_chamber | VALID_FAIL | LLM 节点引用错误: 复杂 3 组件装配中 node_id 引用混乱 | ✅ 增加 prompt 模板 |
| 3 | g23_pipe_reducer | BUILD_FAIL | loft_sections 变径 + flange 装配时 OCCT 失败 | ⚠️ 同 g8 |
| 4 | g24_micro_bushing | VALID_FAIL | 壁厚 0.25mm < 1.0mm preflight margin | ✅ preflight 正确拒绝 |
| 5 | g25_large_ring | VALID_FAIL | 1m 直径环, 壁厚 5mm, 36 个孔与中心孔重叠 | ✅ preflight 正确检测 |

## 三、25 个成功 Case 几何审计

| Case | Volume (mm³) | BBox (mm) | 评估 |
|------|-------------|-----------|------|
| g1_engine_mount | 1,551,179 | [300,200,60] | ✅ 4组件装配, 合理 |
| g2_gearbox_housing | 9,610,218 | [500,475,128] | ✅ 最大体积, 3组件装配 |
| g3_hyd_manifold | 2,993,916 | [150,120,180] | ✅ 6个方向孔(axis=X/Y/Z) |
| g4_pump_casing | 2,784,402 | [250,240,85] | ✅ 3组件蜗壳装配 |
| g5_robot_arm | 2,173,589 | [180,180,500] | ✅ 长管+法兰装配 |
| g6_helix_coil | 675,539 | [561,597,165] | ✅ 20圈螺旋管, 3.7MB STEP! |
| g7_3d_tube | 210,487 | [199,179,474] | ✅ 8点空间管路, BSpline sweep |
| g9_torsion_spring | 84,832 | [212,202,77] | ✅ 15圈扭簧 |
| g10_spiral_volute | 174,939 | [196,196,30] | ✅ 螺旋渐开线蜗壳 |
| g11_pressure_vessel | 920,847 | [310,310,406] | ✅ 薄壁容器 shell 5mm |
| g12_hollow_bracket | 191,902 | [206,166,73] | ✅ 空心支架 shell 3mm |
| g13_enclosure | 859,299 | [308,208,154] | ✅ 电子外壳 |
| g15_heavy_flange | 4,225,309 | [400,400,55] | ✅ 24+12孔重型法兰 |
| g16_stepped_pulley | 1,839,523 | [240,240,87] | ✅ 9段多级带轮 |
| g17_cross_block | 873,863 | [100,100,100] | ✅ 六面钻孔! axis=X/Y/Z 全部正确 |
| g18_ribbed_panel | 2,673,861 | [550,400,35] | ✅ 7纵+5横共12条筋 |
| g19_precision_base | 1,662,390 | [305,280,41] | ✅ 精密基座, 多特征 |
| g20_motor_endbell | 1,046,806 | [250,200,45] | ✅ 电机端盖装配 |
| g21_valve_body | 1,016,418 | [140,140,138] | ✅ 阀体+法兰装配 |
| g22_heat_sink | 1,686,932 | [328,228,104] | ⚠️ MULTI_SOLID(2) |
| g26_extreme_shaft | NEGATIVE | [16,16,500] | ❌ 负体积, 壁厚仅1mm |
| g27_dense_holes | 278,794 | [200,150,10] | ✅ 300个3mm孔! |
| g28_ball_valve | 124,675 | [160,160,160] | ✅ 球阀装配 |
| g29_impeller | 1,072,137 | [300,300,35] | ✅ 离心叶轮装配 |
| g30_hyd_cylinder | 1,661 | [70,70,75] | ✅ 液压缸端盖 |

## 四、系统能力验证

### 验证通过的能力
- ✅ **BSpline 扫掠**: g6(20圈螺旋), g7(8点空间管), g10(渐开线蜗壳)
- ✅ **多轴钻孔**: g3(6方向), g17(六面全方向) — axis=X/Y/Z 全部正确
- ✅ **Shell**: g11(5mm压力容器), g12(3mm空心支架), g13(4mm外壳)
- ✅ **密集特征**: g18(12条筋), g27(300个孔)
- ✅ **复杂装配**: g1(4组件), g2(3组件大体积), g4(蜗壳)
- ✅ **Preflight**: g24(壁厚过薄), g25(孔撞bore) — 正确拒绝

### 暴露的问题
- ⚠️ **Loft**: g8, g23 两个 loft_sections 案例均失败 — OCCT BRepOffsetAPI_ThruSections 不稳定
- ⚠️ **极薄壁**: g26 壁厚 1mm 导致 OCCT boolean 产生负体积
- ⚠️ **多实体装配**: g22 boolean_union 未能合并全部组件 (3层fallback不够)
- ⚠️ **LLM 复杂装配**: g14 节点引用错误 (需要更精确的 prompt 模板)

## 五、与 v5.2 基线对比

| 指标 | v5.2 Full35 | v6.2 Full35 | v6.2 Stress30 |
|------|------------|------------|---------------|
| STEP 生成率 | 27/35 (77%) | 33/35 (94%) | 25/30 (83%) |
| 几何异常 | 1 | 1 | 2 |
| LLM 调用/case | 2.3 | 1.3 | 1.3 |
| 新功能测试 | N/A | 管道/侧孔/shell | **Loft/300孔/六面钻** |

## 六、数据文件位置

```
E:\auto_detection_process\demo_output_v5\v62_stress30_output\
├── results.json              ← 测试结果汇总
├── step_inspection.json      ← 25 case 几何检查数据
├── solidworks/               ← SLDPRT 文件 (导入中)
├── [25个成功case]/           ← 各含: prompt.txt, llm_raw.json, canonical.json,
│                               output.step, autofix_report.json, validation_bundle.json
└── [5个失败case]/            ← 含: llm_raw.json, autofix_report.json (数据保留)
```
