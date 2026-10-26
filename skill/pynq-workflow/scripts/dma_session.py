"""Bounded receive and buffer ownership for PYNQ AXI DMA simple S2MM.

One instance must own a physical DMA. SG, MCDMA and cyclic mode are excluded.
Register layout is the AXI DMA simple-mode S2MM layout, not inferred from names.
"""
import math
import threading
import time
import numpy as np


class ReceiveSession:
    def __init__(self, dma, length_width, alignment=4, allocator=None):
        if not isinstance(length_width, int) or not 8 <= length_width <= 26:
            raise ValueError('Use the actual AXI DMA length width (8..26) from HWH')
        if not isinstance(alignment, int) or alignment < 1 or alignment & (alignment - 1):
            raise ValueError('Alignment must be a positive power of two')
        if allocator is None:
            from pynq import allocate
            allocator = allocate
        self.dma, self.length_width, self.alignment = dma, length_width, alignment
        self.allocator = allocator
        self._retained = None
        self._lock = threading.Lock()

    def receive(self, count, dtype, start, prepare=None, timeout=2.0):
        dtype = np.dtype(dtype)
        if not isinstance(count, int) or count < 1 or dtype.hasobject or dtype.itemsize < 1:
            raise ValueError('Positive count and a plain fixed-size dtype required')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Positive finite timeout required')
        nbytes = count * dtype.itemsize
        if nbytes >= 1 << self.length_width or nbytes % self.alignment:
            raise ValueError('Transfer exceeds BTT capacity or alignment contract')
        with self._lock:
            if self._retained is not None:
                raise RuntimeError('Faulted session; reset and rebind before another receive')
            if prepare:
                prepare()  # deassert/rearm producer and settle configuration before transfer
            buf = self.allocator(shape=(count,), dtype=dtype)
            complete = False
            try:
                self._retained = buf  # also covers a transfer() failure after a partial arm
                self.dma.recvchannel.transfer(buf)
                start()  # arm receive before the producer can emit its first beat
                deadline = time.monotonic() + timeout
                while True:
                    status = self.dma.read(0x34)
                    if status & 0x71:
                        raise RuntimeError(f'S2MM halted/error: DMASR=0x{status:08x}')
                    if status & 2:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'S2MM deadline: DMASR=0x{status:08x}')
                    time.sleep(0.0005)
                self.dma.recvchannel.wait()  # driver invalidation + bookkeeping
                if self.dma.read(0x58) != nbytes:
                    raise RuntimeError('Received byte count differs from interface contract')
                complete = True
                return np.array(buf, copy=True)
            finally:
                if complete:
                    self._retained = None
                    buf.freebuffer()
                # Timeout/error/KeyboardInterrupt leaves a live DMA buffer retained.

    def recover(self, reset_and_rebind):
        """Callback must stop ALL old DMA writes and return a newly bound DMA.

        A callback that fails leaves the buffer retained. Simply changing a
        Python object or stopping a UI loop does not establish hardware quiescence.
        """
        with self._lock:
            replacement = reset_and_rebind()
            if replacement is None or not hasattr(replacement, 'recvchannel'):
                raise ValueError('Recovery must return the DMA bound after a successful hardware reset')
            self.dma = replacement
            if self._retained is not None:
                self._retained.freebuffer()
                self._retained = None
