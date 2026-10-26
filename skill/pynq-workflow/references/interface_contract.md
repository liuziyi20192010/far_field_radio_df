# 接口契约与 Overlay 适配

先从目标工程填写下面的字段，再生成 Python 驱动。字段未确认时不写固定地址或猜测位宽。

| 字段 | 依据 | 改板/改题时是否需重填 |
|---|---|---|
| board、part、镜像、PYNQ/Python 版本 | 实物丝印、Vivado part、目标镜像运行输出 | 是 |
| PS DDR/MIO、PL 时钟/复位、引脚电平 | 板卡原理图、器件手册、XDC、BD | 是，不能迁移旧位流 |
| BIT/HWH/host manifest | 同一次生成的交付包 | 是 |
| IP instance、VLNV、register_map | HWH 与 `overlay.ip_dict`，实际绑定的驱动 | 是 |
| 寄存器偏移、方向、start/rearm/done | RTL/IP 文档；记录每个位的作用与生效时刻 | 是 |
| AXIS 数据宽度、TKEEP、TLAST、帧长 | producer RTL/IP 接口、DMA 配置 | 是 |
| DMA 模式、长度字段、DRE、地址对齐 | HWH 中实际参数 | 是 |
| cache flush/invalidate 与 buffer 生命周期 | PYNQ 驱动行为及共享内存路径 | 是 |
| 校准、有效性标志、黄金参考、误差容限 | 算法及物理信号定义 | 是 |

最小审计契约示例，名称和参数只是示例：

```json
{"ips":{"result_dma":{"parameters":{"C_INCLUDE_SG":"0","C_SG_LENGTH_WIDTH":"20"}}}}
```

manifest 的键相对 manifest 所在目录，值为 `{"bytes":123,"sha256":"..."}`。审计不重写它。明确生成新版包时才刷新哈希，否则旧包被替换也会被误判为正确。

在板上检查实际实例；有层级时沿 hierarchy 的驱动对象取得 IP：

```python
from pynq import Overlay
ol = Overlay('/your/path/demo.bit')
print(ol.ip_dict)
ip = getattr(ol, actual_instance_name)
print(ip.register_map)  # 只有携带寄存器元数据且支持此属性的 IP 才能显示
```

如果自定义模块未导出 `register_map`，记录明确的 MMIO 表，并先做只读检查。不同位流中同一个地址可能属于不同硬件，不能从旧地址表推断新接口。

官方依据：[PYNQ 2.7 Overlay](https://pynq.readthedocs.io/en/v2.7.0/pynq_overlays/loading_an_overlay.html)、[DMA](https://pynq.readthedocs.io/en/v2.7.0/pynq_libraries/dma.html)。
