# 第三方来源与许可证范围

根目录 MIT 只覆盖新增文件和贡献者有权许可的代码，不授予第三方资产的额外权利。此文件记录从现有工程能确认的事实，不替供应商决定授权。

| 路径 / 组成 | 来源与发现 | 当前处理 |
|---|---|---|
| 原工程 `reference/hs_dual_da.v`、`da_wave_send.v` | 正点原子示例，文件声明 Copyright 2023-2033 / All rights reserved | 没有复制进本提交目录；无需它们即可构建 |
| `src/rtl/dac_control.v` | 原工程首行明确称 derived from 上述示例；包含本项目新增握手与流水线 | 保留原来源说明；在能确认衍生许可之前不把这部分声明为 MIT |
| `src/reference/*.xdc`、`rom_1024x10b.coe`，`src/constraints/phase_measure.xdc` | 沿用原 ADC/DAC 教程接口与ROM；未发现可再分发许可证 | 用于精确复现原硬件；开源前向供应商确认可再分发条款，或独立生成允许发布的输入并重新验证 |
| `build/scripts/base_system_bd.tcl` | 原单路DMA工程的PS配置导出 | 核实原工程许可；包含的 DDR/MIO 配置特定于实际板卡 |
| Vivado生成 BD Tcl、HWH、BIT、工具报告及日志 | 由Vivado 2020.2及AMD/Xilinx IP产生 | 工具版权行和来源保留；不把AMD/Xilinx IP实现或EDA安装包纳入MIT；使用遵守厂商条款 |
| NumPy、ipywidgets、PYNQ、Jupyter | 运行时依赖，无源码/vendor目录复制 | 各自原许可证适用，引用官方文档，目标镜像预装为主 |
| `skill/pynq-workflow/`、新增组织/审计/采集脚本、报告正文 | 本次按事实与接口需求编写 | MIT；独立Skill包可复用，不需要上述DAC参考源码 |
| 比赛PDF、PYNQ镜像、供应商原理图、Vivado安装包 | 外部参考/安装资产 | 不附入提交目录或开源仓库，提供文件依据与外部链接 |

公开整个工程前的具体待办：确认以上教学习题/衍生文件的许可；记录许可版本、授权出处和必要版权文本。没有授权依据时不能仅删除版权注释再贴MIT。当前目录是本地整理候选工程，含待核实来源；公开发布是否允许需依据实际授权解决。
