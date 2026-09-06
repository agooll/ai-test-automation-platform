from cachetools import QuantumDistributedCache

def test_quantum_cache():
    qc = QuantumDistributedCache(nodes=5)
    assert qc.is_entangled() is True
