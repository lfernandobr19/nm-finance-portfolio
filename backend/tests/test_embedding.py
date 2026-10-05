"""Embedding client: batch payload, dimension fit, cosine."""

from __future__ import annotations

from app.services.learn.embedding import _fit_dims, cosine, embed


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        return _Resp(
            {
                "embeddings": [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                ]
            }
        )

    def close(self):
        return None


def test_embed_sends_batch_and_dimensions():
    client = _Client()
    vectors = embed(
        ["a", "b"],
        model="nomic-embed-text",
        dimensions=4,
        client=client,
    )
    assert len(vectors) == 2
    url, payload = client.calls[0]
    assert url.endswith("/api/embed")
    assert payload["input"] == ["a", "b"]
    assert payload["dimensions"] == 4
    assert payload["model"] == "nomic-embed-text"
    assert payload["keep_alive"]


def test_fit_dims_truncates_and_renormalizes():
    out = _fit_dims([3.0, 4.0, 0.0], 2)
    assert abs(out[0] - 0.6) < 1e-9
    assert abs(out[1] - 0.8) < 1e-9


def test_cosine_orthogonal_is_zero():
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
