def test_import():
    from schwab_client import SchwabClient
    assert SchwabClient is not None
