import time

def test_time_now():
    now = time.time()
    assert now > 0
