# 远场模拟无线电实时测向系统

2026 全国大学生嵌入式芯片与系统设计竞赛 FPGA 创新设计赛道 AMD 自主选题初级组。英文项目名 `far_field_radio_df`；当前完整工程目录为 `far_field_radio_df_board`。

作品运行于正点原子领航者 ZYNQ7020 开发板。双路 DAC 回环或外部双通道信号模拟双阵元远场输入，PL 完成同步采集、DDC、复共轭乘法和 CORDIC 测相，PS 使用 PYNQ/Python 完成校验、零点校准、FFT 和 Jupyter 展示。相位定义为 CH2−CH1；测向角由 d=λ/4 的远场模型换算。当前是有线等效场景，没有实装 6 m 天线阵列或证明真实无线电外场测向精度。

## 本次更新

2026-10-26 重排 Jupyter 面板，以大号实测相位、测向角和远场模拟场景为主体，频谱作为辅助信息；正常页面移除运行耗时、PL/软件差值等调试内容。维护检查与原始证据采集见 [上板说明](board/README.md) 和 [验证报告](report/verification.md)。本轮为软件与材料更新，保留已验证的 `2026_10_25_dac1_reference_fix` 硬件版本。

用户确认此前同轴线松动，连接修复后系统误差约 ±1°；这是当前用户观察，未附逐帧原始数据，不作为全相位、双模式或长期稳定性的精度保证。此前“最大约 5°”反馈不再作为算法非线性的结论，也没有据此添加相位补偿。

本项目按目录提交，不生成 ZIP。根内 `far_field_radio_df/` 是便于上板复制的运行目录，与 `board/app/` 由部署脚本同步；完整源码、证据和报告保留在本根目录。

## 提交状态

已组织源码、构建入口、仿真、综合实现报告、上板程序、通用 PYNQ Skill、真实公开协作记录与设计报告。正式提交前仍需补齐本版原始实测和参考仪器对比、同条件优化基线、第三方衍生来源授权，以及公开仓库 URL/commit。两路 DAC 已由用户确认恢复正常，不把定性反馈替代版本绑定的 CSV/NPZ。

比赛设计内容见 [设计报告](report/design_report.md)，正确性和性能证据见 [验证报告](report/verification.md)，所选大模型对话的纠错轨迹见 [协作索引](report/collaboration.md)。`report/` 仅保留这些核心报告、优化对比表及真实交互记录。

## 目录对照

```text
far_field_radio_df_board/
  README.md
  license
  third_party_notices.md
  src/                 RTL、PS、约束、BD 与构建输入
  sim/                 验证脚本与结果
  build/scripts/       构建、导出、核查、目录整理入口
  build/reports/       历史与当前综合实现证据
  board/app/           配套 Notebook、Python、BIT/HWH 和 manifest
  board/results/       上板脚本生成的真实证据，禁止伪造补齐
  data/                黄金参考、数据定义与比对
  skill/               通用 PYNQ Skill
  report/              设计报告、验证报告、优化对比及所选协作记录
  far_field_radio_df/   与 board/app 同步的便携运行副本
```

采用指南 3.3.5.4 推荐的七类目录，额外运行副本如上对照。`README.md` 是指南示例名称，`SKILL.md` 是技能入口；其他人工交付文件采用小写英文、数字、下划线或连字符及普通扩展名。可生成的 `build/work/` 和缓存不纳入目录交付清单或 Git。

## 硬件与参数

| 项目 | 参数 / 范围 |
|---|---|
| 板卡 / 器件 | 正点原子领航者 ZYNQ7020 / xc7z020clg400-2 |
| PYNQ 镜像 | 用户确认 `ZYNQ-7020-2.7.0.img`；实际运行版本由采集脚本记录 |
| 工具 | Vivado 2020.2；指南允许其他版本，但须说明并保证脚本复现 |
| ADC / DAC | 双路 10 bit，ADC 50 MSPS，DAC 125 MSPS |
| 信号 / 采样窗 | 12.5 MHz；4096 对样点，81.92 μs |
| DAC 控制 | 相位 1024 级，0.3515625°/级；共同增益 1/256 量化 |
| DMA | simple S2MM，20 bit 长度字段；4112×uint32=16448 bytes/帧 |
| 零点 | 两种模式各自校准 32 个有效且流水线一致的帧；改变 DAC 增益后重校 |
| 显示调度 | 相位目标 20 Hz，频谱 5 Hz，历史/场景 10 Hz；目标不等于实测 FPS |
| 方向模型 | θ=arcsin(Δφ/90°)，物理解为 ±90°相位内，端点容差 0.25° |

FFT 在 Python，测相在 PL；采样帧内连续、帧间有间隔。DAC 关闭输出中点码 512，不等同于模拟端口高阻。内部时序通过不能代替外部 ADC/DAC 电气量程与 I/O 延迟预算确认。

## 从零复现

Windows PowerShell，Python 3.8+。离线测试不需要安装 PYNQ；开发板运行使用目标镜像自带环境。

```powershell
Set-Location E:\PYNQ\fpgachina\far_field_radio_df_board
python -m pip install -r requirements.txt
python -m unittest discover -s sim -p 'test_*.py' -v
python build/scripts/run_build.py --vivado D:/Xilinx/Vivado/2020.2/bin/vivado.bat
python build/scripts/check_artifacts.py --built
python skill/pynq-workflow/scripts/report_metrics.py build/reports/current --output build/reports/current/metrics.json
python build/scripts/prepare_submission.py
```

路径从脚本位置定位，迁移不依赖旧 `phase_measure` 源目录。首次自动创建 XPR；完整构建需安装 Vivado 2020.2 与 Zynq-7000 支持。未宣称已用 2025.2/2026.1 复验。只做 RTL 仿真可加 `--simulate-only`；内部组件名称 `phase_measure` 表示测相模块，作品展示名以上述标题为准。

只改软件时执行 `python build/scripts/deploy.py --software-only`，先核对硬件文件和硬件源哈希，再同步运行副本。硬件变化必须重新构建。`prepare_submission.py` 核验目录并刷新提交清单，不产生压缩包；不会把未完成的板级数据、许可和发布项改为完成。

## 上板演示与实测

上传整个 `board/app/` 的内容或根内 `far_field_radio_df/` 到 Jupyter 的独立目录，保持 `overlay/` 相对位置。更新后重启 kernel，打开 `far_field_radio_df.ipynb`。

板载模式接 DAC1→ADC1、DAC2→ADC2；外部模式使用相干、等幅的双路 12.5 MHz 信号。先确认同轴线紧固、两路有信号且无削顶，再做本模式 0°校准并开始。切换外部输入前关闭板载输出、停止刷新并正确更换连接。板载模式改变增益后需要重新校准。

比赛原始证据可在完整工程复制到板上后采集：

```bash
python3 board/collect_measurements.py --mode dac --zero-ready --frames 20
```

若只需无界面的单个设定相位记录，停止并关闭旧 Dashboard/仪表对象后，在运行目录执行：

```bash
python3 profile_pynq.py --dac-phase -45 --gain 0.5 --zero-ready --frames 200 --verify-manifest
```

后者先置 0°校准，再设为 -45°，记录原始帧、CSV、统计和版本。维护过程及外部模式采集详见 [board/README.md](board/README.md)。一个物理 DMA 只由一个仪表对象拥有。

## 通用技能与协作记录

[Skill 说明](skill/README.md)逐项列出适用场景、调用、验证效果、失败来源与边界。技能抽离 Overlay 契约、同构建审计、DMA 所有权和黄金比对，不写死本作品的载频、ADC 格式、引脚与 DMA 名称；换板需重新提供硬件契约，未宣称跨板物理验证。

[公开协作原文](report/interaction/transcript.md)仅保留用户指定的“目前项目已经能够测量两路信号相位差”对话，共 19 条公开消息；其他历史会话与当前整理会话均未纳入提交。保留时间、模型标识和源行号；导出范围由 `build/config/interaction_selection.json` 限定。[纠错索引](report/collaboration.md)仅分析这段对话。其他技术报告和通用 Skill 属于工程材料，不冒充原始对话。验证材料的脱敏说明已合并到 [验证报告](report/verification.md)。

## 许可与发布

有权许可的原创技能、脚本和正文采用 [MIT](license)。第三方衍生文件与厂商 IP 不因根目录 MIT 自动取得再分发授权；先完成 [来源核实](third_party_notices.md)，再公开 GitHub/Gitee 仓库并记录真实 URL 和版本。当前没有创建或推送远程仓库。
