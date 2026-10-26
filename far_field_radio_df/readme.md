# 远场模拟无线电实时测向系统上板运行与证据采集

硬件为正点原子领航者 ZYNQ7020，目标器件 `xc7z020clg400-2`，用户确认镜像 `ZYNQ-7020-2.7.0.img`。ADC/DAC 实际型号、模拟输入范围及编码须按板卡资料确认，不能猜测。

本项目采用目录交付。`board/app/` 是标准部署目录；完整工程根内 `far_field_radio_df/` 是同步的便携运行副本。将其中一个目录整体复制到板上，不混用新旧 Python 与 BIT/HWH。完整比赛采集脚本 `collect_measurements.py` 还需要完整工程结构。

当前硬件标识为 `2026_10_25_dac1_reference_fix`，已修复 DAC1 实现后查表地址恒为零的问题，并通过路由后两路输出仿真；用户已确认两路 DAC 恢复正常。本轮面板更新不改变该硬件。用户纠正此前同轴线松动，修复连接后观察到约 ±1°误差；尚无本版逐帧原始数据证明全范围精度。

## 界面运行

1. 用目标镜像启动并访问 Jupyter；复制完整运行目录，保留 `overlay/` 与 Python 的相对位置。
2. 核对 manifest，重启 kernel，打开 `far_field_radio_df.ipynb` 执行初始化。
3. 数字计数自检用于维护时验证搬运，不能说明模拟输入正确；维护操作见下文“维护与诊断”。
4. 板载模式连接 DAC1→ADC1、DAC2→ADC2；外部模式连接相干、等幅双路 12.5 MHz 输入。先检查同轴插头紧固、两路信号存在、量程正确且无 OTR。
5. 同相输入下校准该模式的 32 个有效帧，再开始刷新。两模式分别保存零点；改变 DAC 增益后重新校准。
6. 切换外部输入前停止刷新并关闭板载输出，再更换接线，避免两个信号源同时驱动同一 ADC。更新 BIT/HWH/驱动后统一复制并重启 kernel、重新校准。

新版主界面放大相位和测向角，突出等效远场场景，频谱作为辅助；调试耗时、原始幅度和流水线差值不占用演示视图。信号异常、校准未完成和模型越界仍须明确显示。相位目标 20 Hz、频谱 5 Hz、历史/场景 10 Hz 是调度目标，不是新版实板 FPS 结论。

显示平滑只影响可视读数，不替换原始测量；正式误差统计使用采集脚本的原始校正相位。有效相位超出几何模型范围时，仍保留测相读数，但不输出虚假方向角。

## 连接与校准故障

稳定偏差突然增大时，先固定输入，核验两路输出、同轴连接、共地、量程和仪器相位基准，再分析算法。零点校准不能修复接触不良、削顶或缺失信号，平滑也不能消除稳定偏差。不要根据一个错误相位点添加补偿。

校准只接收有效且流水线一致的帧，最多补采 8 帧；持续异常仍中止并清除旧零点。失败原始包与逐次诊断自动保存在运行目录 `diagnostics/calibration_failure_*.npz`。维护时保留该文件；正常面板只需提供简洁、可操作的错误提示。一个物理 DMA 始终只保留一个驱动所有者；采集脚本运行前先关闭 Dashboard 和旧 `pm`。

## 无界面误差与耗时记录

在板端运行目录执行：

```bash
python3 profile_pynq.py --dac-phase -45 --gain 0.5 --zero-ready --frames 200 --verify-manifest
```

工具加载新 Overlay，先置 0°校准，再切至 -45°采集，退出关闭 DAC；`--fft` 可记录每帧 FFT 成本。不传 `--dac-phase` 时保持 DAC 关闭用于外部输入。输出原始 words NPZ、逐帧 CSV、误差均值/标准差/峰峰值、耗时及版本；原始数据保存处理在采集后执行，工具不测浏览器绘制 FPS。

## 比赛多点实测

将完整工程复制到板上、关闭界面后，在工程根目录执行：

```bash
python3 board/collect_measurements.py --mode dac --zero-ready --frames 20
```

`--zero-ready` 表示真实同相信号已经准备好。DAC 模式先校正 0°，再采集多个相位；检查两个物理回环和量程。外部模式先在信号源设同相输入，校正完成后按提示改为参考相位：

```bash
python3 board/collect_measurements.py --mode external --zero-ready --reference-deg 45 --frames 20
```

两路外部信号需共用时基且频率相同；不要用两台互不相干的信号源设定值直接当稳定相位参考。实际源幅度与负载设定依 ADC 量程和仪器说明确认，不在此猜电压值。

`board/results/run_.../` 包含逐帧 NPZ、CSV 与 metadata，不编辑原始 words。对同帧软件参考示例：

```bash
python3 skill/pynq-workflow/scripts/golden_compare.py board/results/run_.../frame_0001.npz --circular --tolerance 0.02
```

0.02°只用于数字 PL 与同帧软件核对，不是整条模拟链路精度承诺。DAC/信号源参考与实测还包含线缆、量化、滤波和模拟通道误差，须单独统计。

补充至少多个独立相位点、弱信号/OTR、重新校准、持续运行和实际刷新率；保存接线照片、信号源/示波器设定与参考截图。文件名用英文，例如 `wiring.png`、`scope_zero.png`、`runtime.csv`。采集后将真实结果复制回目录并更新报告和状态。

目前旧版 5.9 FPS、约 60 ms 和 0°/±45°范围，以及本次约 ±1°均为用户面板观察，不能代替与本次 manifest 绑定的原始实测。主机字段解码时间与包含 DMA 的 capture 时间不能直接相除称系统加速比。


## 维护与诊断

先检查同轴线锁紧、通道对应、两路有输出、幅度/偏置/负载及校准条件。主界面不显示调试量，维护可先停止并关闭面板，保留pm对象，在单独单元查看同帧结果：

```python
from phase_measure import diagnose_frame
frame = pm.capture()
print(diagnose_frame(frame))
print('PL / 软件相位', frame['raw_phase_deg'], frame['software_phase_deg'])
print('幅度 / 超量程', frame['amplitude'], frame['overrange'])
print('流水线一致', frame['pipeline_consistent'])
```

校准使用32个有效且流水线一致的帧，最多补采8帧；不能通过放宽有效性门限掩盖弱信号或接线故障。失败后查看 `pm.last_calibration_report`，原始诊断自动保存在 `diagnostics/calibration_failure_*.npz`。

`ui.close()` 停止刷新并关闭DAC，`pm.close()` 释放空闲DMA缓冲。DMA超时后保留可能仍被硬件访问的缓冲；停止刷新后使用 `pm.recover()` 重载Overlay，再重新校准。关闭DAC表示中点码输出，不代表端口高阻。系统验证与故障证据见完整工程的 `report/verification.md`。
