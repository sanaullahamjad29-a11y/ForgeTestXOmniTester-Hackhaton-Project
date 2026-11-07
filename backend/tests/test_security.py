from fastapi import HTTPException
from app.security import validate_url, build_containment_receipt


def test_blocks_localhost():
    try:
        validate_url("http://localhost:8000")
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    raise AssertionError("Expected HTTPException for localhost")


def test_blocks_file_scheme():
    try:
        validate_url("file:///etc/passwd")
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    raise AssertionError("Expected HTTPException for file:// scheme")


def test_blocks_typo_protocol_httttps():
    try:
        validate_url("httttps://youtchbdsbcdbcjcbdbhbvhsbvube.com")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "protocol" in str(exc.detail).lower()
        return
    raise AssertionError("Expected HTTPException for httttps:// typo protocol")


def test_blocks_url_credentials():
    try:
        validate_url("https://user:pass@example.com")
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    raise AssertionError("Expected HTTPException for embedded URL credentials")


def test_containment_receipt_includes_sha256_and_isolation_flags():
    receipt = build_containment_receipt("unit_test", {"hello": "world"})
    assert len(receipt["sha256"]) == 64
    assert "--rm" in receipt["isolation_flags"]
    assert "secrets-mounted=false" in receipt["isolation_flags"]
