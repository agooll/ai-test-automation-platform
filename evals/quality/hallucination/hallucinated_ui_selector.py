def test_invented_ui_element(page):
    page.goto("https://app.example.com")
    page.click("#btn-nonexistent-magic-submit")
    assert page.is_visible(".fake-success-banner")
