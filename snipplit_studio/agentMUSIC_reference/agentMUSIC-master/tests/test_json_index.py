from modules.json_index import load_json_list, save_json_atomic


def test_json_index_roundtrip(tmp_path):
    index_path = tmp_path / "index.json"
    payload = [{"id": "one"}, {"id": "two", "value": 2}]

    save_json_atomic(index_path, payload)

    assert load_json_list(index_path) == payload
    assert not list(tmp_path.glob("*.tmp"))
