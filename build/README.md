# 构建工程、报告与交付

源码的完整工程表示为RTL/XDC、PS Python、ROM/约束输入、base_system_bd.tcl的PS配置，以及create_project.tcl的连接/地址/复位/时钟规则。run_build.py从这些输入创建完整XPR/BD，再仿真、综合实现、同次导出BIT/HWH、检查引脚和部署。src/bd中保存本次生成的完整BD及wrapper快照供审阅；构建以脚本为入口。

本地build/work/vivado/phase_measure/phase_measure.xpr为实际生成并经迁移核查的工程，可以打开。ZIP/Git排除build/work自动生成缓存和重复IP产物；从零复现会重新生成它们，不依赖外部phase_measure项目、原电脑绝对路径或OOC检查点。build/reports/historical为未改写的旧工具证据，current为本次真实构建，包括第一次失败日志与修复后输出。

命令、版本与适用检查详见根README。--built比对交付BIT/HWH与本地实现；普通check_artifacts只读检查manifest和HWH契约，适合解压后没有build/work的交付包。部署生成新版文件后才使用--refresh。

提交状态核查：`python build/scripts/verify_submission.py`检查工程候选包；`--strict`会因当前实测/基线/授权/发布待办返回非零。此状态检查保留事实，不能用改状态JSON代替实际证据。
