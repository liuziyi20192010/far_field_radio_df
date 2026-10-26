# 仿真与离线验证

`tb_phase_measure.sv`为11帧采集/测相/反压/复位验证，`tb_dac_control.sv`验证配置切换和精确相位/Q6输出，并在gain=0.5下遍历全部1024相位码；`tb_cordic_phase.sv`为两幅度逐角参考。执行build/scripts/run_build.py后检查三个实际PASS标记；最新工具日志在build/reports/current/simulate.log。本目录results包含Python行为验证及交付核查，historical保留先前证据。

`tb_dac_implemented.sv`与 `build/scripts/check_dac_implemented.tcl`对路由后的DAC原语网表执行独立数学参考检查，覆盖两路幅度、相位、周期、谐波、禁用/恢复和转发时钟。旧缺陷版会因CH1幅度为0失败，新版10种设置通过。构建部署门控要求实际 `DAC_IMPLEMENTED_PASS`，并以 `implemented_bit.sha256` 绑定所验证的位流；仅RTL仿真或进程返回0不足以放行。

离线命令：`python -m unittest discover -s sim -p 'test_*.py' -v`，2026-10-25最新主工程58项通过。涵盖整数四相参考、DMA复用/快照/中断保护、32帧校准/补采/诊断回放、分频频谱源帧、完整周期/滚动FPS、原始误差保留、CSV/NPZ记录、软件部署与实现后证据门控，以及两种无关IP契约/负载。mock不是板级实测。

数据比对：`python skill/pynq-workflow/scripts/golden_compare.py data/reference/rtl_phase_comparison.npz --circular --tolerance 0.35`。工具表解析遇未知字段拒绝输出零值。完整验证边界见report/verification.md。
