# 通用 PYNQ 技能包

目标：把 Overlay 一致性、DMA 缓冲区所有权、接口契约和黄金参考比对从测向题目中抽离。另一个队伍可整体复制 `pynq-workflow/`，再提供自己的 JSON 契约、回调和测试数据；脚本不导入本项目驱动、不写死频率、帧长、引脚或 DMA 实例名。代码许可为根目录 MIT。

## 技能目录

| 项目 | 适用场景 / 使用方法 | 起因与已验证效果 | 失效条件 / 边界 |
|---|---|---|---|
| Overlay 契约核查 | 有同名 BIT/HWH 的 PYNQ 工程；`overlay_audit.py --bit demo.bit --contract contract.json --manifest manifest.json` | 板上相位异常时需要排除旧 BIT、HWH、Python 混包；本项目 HWH 实际检查和两套不同 IP 名/长度宽度的离线契约检查；篡改文件会失败且不会重写 manifest | 只查元数据/哈希；不证明芯片、电平、位流功能；非 HWH 平台需换解析器 |
| DMA 有界接收 / 所有权 | simple AXI DMA S2MM；实例化 `ReceiveSession(dma, length_width, alignment)`，传入 `prepare/start` 回调 | 16448 字节超过原 14 bit 长度字段；中断/超时不能立即释放 DMA 内存；128 个 uint16、8192 个 uint32 两套不同负载通过；注入超时、错误和 KeyboardInterrupt 后保留内存，成功复位后才释放 | 不支持 SG、MCDMA、持续环形模式；真实硬件 reset/quiescence 必须由调用者实现；单实例锁不解决多个独立驱动争用同一 DMA |
| 黄金参考比对 | NPZ 内有 `actual/reference`；线性量直接比，角度用 `--circular` | ±180°附近直接相减产生伪大误差；离线线性、圆周、非有限值检查通过；本工程同帧 DFT/PL 分级核对通过已有协议测试 | 不代替参考信号源测量；容差由量化、噪声和应用要求确定；零信号/OTR不能靠放大容差通过 |
| 报告指标采集 | Vivado 资源/时序摘要表；`report_metrics.py reports --output metrics.json` | 旧验证说明与真实报告 LUT/FF 数值不一致；本项目原始报告成功解析，缺项/未知格式拒绝伪造零 | 仅识别列出的资源表标题；内部裕量不能代表外部 ADC/DAC I/O 时序签核；版本改表需扩展解析器 |
| 接口契约与排查清单 | 新板卡、新加速核或接口迁移；按 references 文件填写契约并逐层定位 | PL 与软件分歧、DAC 配置跨周期混样、频谱降采样丢峰等真实反馈可追溯到历史对话 | 具体硬件数值不能照搬；多比特 CDC 需握手/稳定窗口，不能只加两个触发器 |
| 提示词工作流 | 人工需求→模型建议→工具证据→纠错；读取 `references/prompts.md` | 后写模板来自工程经验；`report/interaction/` 仅保留用户指定的 GUI 对话，不包含所有经验来源的原始对话 | 模板未在多模型/多板卡上做稳定性统计，不宣称固定成功率 |
| 测量展示与证据保留 | 简化 Jupyter 主界面或排查稳定偏差时读取 `references/presentation_and_evidence.md`；核心量和场景优先，诊断由维护入口/原始文件保留 | 来自本轮面板重排与用户同轴线松动纠正；离线状态测试保留弱信号、超量程、分模式校准和无效方向，真实生产 HTML/SVG 已渲染目视检查 | 静态预览使用合成数据，不是上板精度/FPS证据；物理连接排查不能替代独立仪器与多点标定，没有跨板统计 |

## 最小复用步骤

1. 将 `pynq-workflow` 复制到可发现的技能目录；Codex 可放到用户的 `.codex/skills/`，用 `$pynq-workflow` 调用。其他模型直接读取 `SKILL.md`。
2. 从实际 HWH/RTL 填写契约，不把示例当成硬件参数。建立一次构建的 SHA256 manifest。
3. 导入 `scripts/dma_session.py`，提供接收对象、真实长度字段及复位/启动回调。
4. 接收已知向量，保留原始帧；为自己的算法提供黄金参考和容差。
5. 在目标板记录镜像、Python/PYNQ、器件、时钟、CSV/NPZ、报告与失败记录。

离线复用验证：`python -m unittest discover -s sim -p test_skill.py -v`。其中两种契约及负载都是测试夹具，不是第二块开发板的实测。支持 Python 3.8+、NumPy；Overlay 审计仅需标准库。真实 PYNQ 路径以 2.7 镜像为目标，最终仍要在用户开发板运行。

`SKILL.md` 是技能框架固定入口，`README.md` 是指南明确列出的文件名；两者采用标准拼写，其余人工交付命名采用小写英文。技能包将技术边界、证据等级和适配参数一起交付，通用性不等同于任意板卡零配置加载同一位流。
