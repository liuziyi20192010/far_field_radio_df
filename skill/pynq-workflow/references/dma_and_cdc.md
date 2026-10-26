# DMA、缓存与时钟域

适用：有限帧 simple AXI DMA S2MM。`ReceiveSession` 默认以 32 bit stream 常见的 4 字节对齐为例；从 HWH 确认实际模式、DRE、宽度、BTT 位数后传入参数。计数×dtype.itemsize 是字节数，包含包头；接收长度必须与 TLAST 实际完成帧一致。长度字段 W 的非零可表达最大值是 `2**W - 1`。DRE 关闭时遵守驱动要求的地址和传输对齐。

```python
from dma_session import ReceiveSession
session = ReceiveSession(dma_object, length_width=actual_btt_width,
                         alignment=actual_alignment)
data = session.receive(actual_count, actual_dtype,
                       prepare=deassert_start_and_set_mode,
                       start=assert_producer_start, timeout=2.0)
# 回调必须完成硬件复位并确保旧 DMA 不再写，再返回新绑定的 DMA：
# session.recover(reset_overlay_and_return_new_dma)
```

不把普通 `np.ndarray` 当 DMA buffer。使用 `pynq.allocate`，不要让 DMA 写到已 freebuffer 的物理地址。发送前 CPU 写入需要设备可见；接收完成需要 CPU 可见。PYNQ simple 驱动通常在 transfer/wait 内执行对应 flush/invalidate，应核对目标版本源码；直接 MMIO 操作时须显式承担缓存维护。收发两端存在依赖时先 arm 接收再启动产生输出的一端，以避免死锁或丢首拍。

超时和 Ctrl+C 不是硬件已停的证据。保留出错缓冲，阻止复用；停止所有后台调用，成功复位 DMA 或重新配置 Overlay，确认旧总线写入结束，再释放缓冲。恢复回调的可靠性超出离线 mock 的证明范围。不要只调用 `freebuffer()` 或换 Python 对象。新 Overlay 会重置其他 PL 外设，恢复策略须覆盖这些实际影响。

AXIS 反压时，直到 `TVALID && TREADY` 握手前保持 TDATA/TKEEP/TLAST 稳定。计数与 TLAST 根据成功握手推进。不同 clk 的 AXIS 需要异步 FIFO/协议桥。单 bit 状态可同步，多 bit 配置通常需要 source 保持、请求、目的域原子应用、ack；两个同步寄存器本身不能保证总线原子性。reset 释放在各自域同步并等待时钟稳定。

FIFO 已接受 TLAST 的 done 不等于 DMA 已写完 DDR。分别检查 producer、FIFO、DMA 状态。抓包头、帧序号、负载计数和真实接收字节数。

官方依据：[PYNQ 2.7 DMA](https://pynq.readthedocs.io/en/v2.7.0/pynq_libraries/dma.html)、[DMA 源码](https://pynq.readthedocs.io/en/v2.7.0/_modules/pynq/lib/dma.html)、[PYNQ allocate](https://pynq.readthedocs.io/en/v2.7.0/pynq_libraries/allocate.html)。
