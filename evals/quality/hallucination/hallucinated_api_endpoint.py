import requests

def test_invented_endpoint():
    res = requests.get("https://api.example.com/api/v99/fake_unregistered_endpoint")
    assert res.status_code == 200
