# 商业 CAD 独立导入实验（SolidWorks 2025）

- 软件：SolidWorks 2025（COM 自动化，revision 33.5.0）
- 样本：从 400 次主实验成功样本中固定随机抽取 80 个 STEP
- 直接导入为单一实体：80/80 = 100.00%
- 首次尝试直接导入率：96.25%
- 瞬时失败经重试成功：3 个

说明：体积/尺寸校验由 OpenCascade 指标（volume_relative_error / key_dimension_relative_error）补充；
SolidWorks 用于验证商业 CAD 可直接导入并形成单一实体。