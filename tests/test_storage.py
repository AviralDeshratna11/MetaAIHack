import io

import pytest
from botocore.exceptions import ClientError

from packages.common.storage import Storage
from packages.common.utils import DomainError, file_hash


@pytest.mark.parametrize("existing", [b"same bytes", b"different bytes"])
def test_handoff_write_recovery_reuses_only_identical_immutable_content(tmp_path, existing):
    path = tmp_path / "handoff.json"
    path.write_bytes(b"same bytes")
    store = object.__new__(Storage)
    store.bucket = "test"
    class Client:
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(existing)}
        def head_object(self, **kwargs):
            return {"ContentLength": len(existing), "Metadata": {"sha256": file_hash(path)}}
    store.client = Client()
    if existing == path.read_bytes():
        store.upload(path, "immutable-handoff", "application/json", reuse_identical=True)
    else:
        with pytest.raises(DomainError) as exc:
            store.upload(path, "immutable-handoff", "application/json", reuse_identical=True)
        assert exc.value.code == "E_ARTIFACT_CONFLICT"
    with pytest.raises(ClientError):
        store.upload(path, "immutable-handoff", "application/json")
