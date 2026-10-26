"""Behavior checks using two different application contracts and injected DMA faults."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skill/pynq-workflow/scripts'))
from overlay_audit import audit
from dma_session import ReceiveSession
from golden_compare import compare


class Buffer(np.ndarray):
    def freebuffer(self): self.freed = True


class FakeDMA:
    def __init__(self, status=2, interrupt=False):
        self.recvchannel = self
        self.status, self.interrupt = status, interrupt
        self.events = []
    def transfer(self, buffer):
        self.buffer = buffer
        buffer[:] = np.arange(buffer.size)
        self.events.append('transfer')
    def read(self, offset):
        return self.status if offset == 0x34 else self.buffer.nbytes
    def wait(self):
        self.events.append('invalidate')
        if self.interrupt: raise KeyboardInterrupt


class Tests(unittest.TestCase):
    def allocate(self, **kwargs):
        self.buffer = np.zeros(**kwargs).view(Buffer)
        self.buffer.freed = False
        return self.buffer

    def test_two_unrelated_overlay_contracts_and_immutable_hash(self):
        for name, width in [('counter_rx', '14'), ('vector_result', '20')]:
            with tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                bit = temp / 'demo.bit'
                bit.write_bytes(b'mock-bit-for-metadata-test')
                bit.with_suffix('.hwh').write_text(f'<ROOT><MODULE INSTANCE="{name}"><PARAMETERS>'
                    f'<PARAMETER NAME="C_SG_LENGTH_WIDTH" VALUE="{width}"/></PARAMETERS></MODULE></ROOT>')
                contract = {'ips': {name: {'parameters': {'C_SG_LENGTH_WIDTH': width}}}}
                manifest = temp / 'manifest.json'
                manifest.write_text(json.dumps({p.name: {'bytes': p.stat().st_size,
                    'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in temp.iterdir() if p.suffix in ['.bit', '.hwh']}))
                self.assertEqual(audit(bit, contract, manifest)['status'], 'pass')
                original = manifest.read_bytes()
                bit.write_bytes(b'changed')
                with self.assertRaises(ValueError): audit(bit, contract, manifest)
                self.assertEqual(manifest.read_bytes(), original)

    def test_different_counts_dtypes_receive_before_start_and_copy(self):
        for count, dtype, align in [(128, 'uint16', 2), (8192, 'uint32', 4)]:
            dma = FakeDMA()
            session = ReceiveSession(dma, 20, align, self.allocate)
            result = session.receive(count, dtype, lambda: dma.events.append('start'))
            self.assertEqual(dma.events, ['transfer', 'start', 'invalidate'])
            self.assertTrue(self.buffer.freed)
            self.assertTrue(np.array_equal(result, np.arange(count, dtype=dtype)))
            self.buffer[:] = 0
            self.assertEqual(int(result[-1]), count - 1)

    def test_timeout_retains_memory_until_successful_reset(self):
        dma = FakeDMA(status=0)
        session = ReceiveSession(dma, 20, allocator=self.allocate)
        with self.assertRaises(TimeoutError): session.receive(16, 'uint32', lambda: None, timeout=0.001)
        self.assertFalse(self.buffer.freed)
        with self.assertRaises(RuntimeError): session.receive(16, 'uint32', lambda: None)
        def failed_reset(): raise RuntimeError('hardware reset failed')
        with self.assertRaises(RuntimeError): session.recover(failed_reset)
        self.assertFalse(self.buffer.freed)
        session.recover(lambda: FakeDMA())
        self.assertTrue(self.buffer.freed)

    def test_interrupt_and_error_retain_buffer(self):
        for dma, error in [(FakeDMA(interrupt=True), KeyboardInterrupt), (FakeDMA(status=0x10), RuntimeError)]:
            session = ReceiveSession(dma, 20, allocator=self.allocate)
            with self.assertRaises(error): session.receive(16, 'uint32', lambda: None)
            self.assertFalse(self.buffer.freed)

    def test_length_and_alignment(self):
        session = ReceiveSession(FakeDMA(), 14, allocator=self.allocate)
        with self.assertRaises(ValueError): session.receive(4112, 'uint32', lambda: None)
        with self.assertRaises(ValueError): session.receive(3, 'uint16', lambda: None)

    def test_linear_and_circular_goldens(self):
        self.assertTrue(compare([1, 2, 3], [1, 2, 3], 0)['passed'])
        self.assertFalse(compare([1, 2, 4], [1, 2, 3], 0.5)['passed'])
        self.assertTrue(compare([179.9], [-180.0], 0.11, circular=True)['passed'])
        self.assertFalse(compare([float('nan')], [0], 1)['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
