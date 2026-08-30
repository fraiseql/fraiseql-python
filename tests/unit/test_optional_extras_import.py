"""Import guards for the optional extras whose versions moved in a security bump.

The existing integration tests for the LangChain and LlamaIndex vector stores fall
back to ``Mock`` when the upstream import fails, so a broken extra reads as a pass.
That is the right behaviour for a suite that must run without the extras installed
— but it means nothing checks the upgraded libraries actually import.

These tests skip when the extra is absent and **fail** when it is present but
broken, which is the shape that catches API drift from a version bump.
"""

import importlib

import pytest

# module under test -> the upstream import it needs, and the extra that provides it
INTEGRATIONS = [
    ("fraiseql.integrations.langchain", "langchain_core.documents", "langchain"),
    ("fraiseql.integrations.llamaindex", "llama_index.core.schema", "llamaindex"),
]


@pytest.mark.parametrize(("module", "upstream", "extra"), INTEGRATIONS)
def test_integration_module_imports_with_its_upstream(
    module: str, upstream: str, extra: str
) -> None:
    pytest.importorskip(upstream, reason=f"the {extra} extra is not installed")
    importlib.import_module(module)


def test_pypdf_reader_api_is_present() -> None:
    """``pypdf`` moved 6.14 → 6.16 for GHSA-fp3f-mc75-235c / GHSA-fwg2-594c-jp42."""
    pypdf = pytest.importorskip("pypdf", reason="the llamaindex extra is not installed")
    assert hasattr(pypdf, "PdfReader")


def test_nltk_data_load_is_present() -> None:
    """``nltk`` moved 3.9 → 3.10 for four path-traversal / SSRF / ReDoS advisories.

    ``nltk.data.load`` is the function three of them are about; it is reached
    through LlamaIndex's sentence splitting, never called by FraiseQL directly.
    """
    pytest.importorskip("nltk", reason="the llamaindex extra is not installed")
    import nltk.data

    assert callable(nltk.data.load)


def test_aesgcm_still_imports_from_cryptography() -> None:
    """``cryptography`` moved 49 → 50 for GHSA-g6cj-pr64-35w5.

    That advisory is a Bleichenbacher oracle in PKCS#7 ``EnvelopedData`` decryption,
    which FraiseQL does not call — the only cryptography API it uses is AES-GCM, in
    the KMS key manager and its local provider. This is the import that has to keep
    working for every install, since ``pyjwt[crypto]`` puts cryptography in the
    default dependency tree.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = AESGCM.generate_key(bit_length=256)
    aead = AESGCM(key)
    nonce = b"\x00" * 12
    assert aead.decrypt(nonce, aead.encrypt(nonce, b"payload", None), None) == b"payload"
