def test_create_app_registers_receive_and_file_routes():
    from hdmi_exfil.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)

    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/api/receive/start" in rules
    assert "/api/receive/file/<path:filename>" in rules
