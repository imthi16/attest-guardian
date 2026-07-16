"""The placeholder scanner must flag EICAR and pass everything else."""

from app.ingestion.scanner import EICAR_SIGNATURE, SignatureScanner


async def test_eicar_is_flagged() -> None:
    verdict = await SignatureScanner().scan(b"prefix " + EICAR_SIGNATURE + b" suffix")
    assert not verdict.clean
    assert verdict.reason == "eicar-test-signature"


async def test_ordinary_content_is_clean() -> None:
    verdict = await SignatureScanner().scan(b"%PDF-1.7 an ordinary document")
    assert verdict.clean
    assert verdict.reason is None
