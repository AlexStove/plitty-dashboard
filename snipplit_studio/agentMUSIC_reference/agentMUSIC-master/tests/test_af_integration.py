"""Tests for the AF platform integration surface:

SubmitVideoRequest contract, API-key auth posture, provider_status mapping,
job_store persistence + atomic command_id idempotency, and restart reconcile.
"""

import dataclasses
import threading

import pytest
from pydantic import ValidationError

import modules.auth as auth
import modules.job_store as job_store
from modules.config import Settings
from modules.job_tracker import Job, JobTracker
from modules.validation import SubmitVideoRequest


# ── SubmitVideoRequest ──────────────────────────────────────────────────────

def test_submit_requires_exactly_one_source():
    with pytest.raises(ValidationError):
        SubmitVideoRequest(command_id="cmd-1")
    with pytest.raises(ValidationError):
        SubmitVideoRequest(command_id="cmd-1", track_id="t1", prompt="song")


def test_submit_rejects_count_above_one():
    with pytest.raises(ValidationError):
        SubmitVideoRequest(command_id="cmd-1", prompt="song", count=2)


def test_submit_accepts_single_source_and_defaults():
    req = SubmitVideoRequest(command_id="cmd-1", minio_key="Artist/Song.mp3")

    assert req.source == ("minio_key", "Artist/Song.mp3")
    assert req.count == 1
    assert req.bg_type == "animated"
    assert req.aspect == "portrait"


def test_submit_requires_command_id():
    with pytest.raises(ValidationError):
        SubmitVideoRequest(prompt="song")


def test_submit_rejects_non_spotify_url():
    with pytest.raises(ValidationError):
        SubmitVideoRequest(command_id="cmd-1", spotify_url="https://example.com/x")


# ── Auth posture ────────────────────────────────────────────────────────────

def _settings(**overrides) -> Settings:
    return dataclasses.replace(Settings(), **overrides)


def test_auth_fail_open_only_in_local(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(environment="local", api_keys=()))
    auth.require_api_key(x_api_key=None)  # no exception


def test_auth_fail_closed_outside_local(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(auth, "settings", _settings(environment="production", api_keys=()))
    with pytest.raises(HTTPException) as exc:
        auth.require_api_key(x_api_key=None)
    assert exc.value.status_code == 503


def test_auth_rejects_wrong_key_and_accepts_valid(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        auth, "settings", _settings(environment="production", api_keys=("secret",))
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_api_key(x_api_key="wrong")
    assert exc.value.status_code == 401
    auth.require_api_key(x_api_key="secret")  # no exception


# ── provider_status mapping ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status,phase,expected",
    [
        ("running", "queued", "queued"),
        ("running", "rendering", "running"),
        ("done", "done", "succeeded"),
        ("error", "error", "failed"),
        ("stopped", "stopped", "canceled"),
    ],
)
def test_provider_status_mapping(status, phase, expected):
    job = Job(job_id="j1", user_id=1, status=status, current_phase=phase)

    assert job.provider_status == expected
    assert job.to_dict()["provider_status"] == expected


# ── job_store persistence + idempotency ─────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "settings", _settings(output_dir=str(tmp_path)))
    local_tracker = JobTracker(max_history=50)
    monkeypatch.setattr(job_store, "tracker", local_tracker)
    local_tracker.set_persist_hook(job_store.persist_job)
    return local_tracker


def test_job_store_round_trip(store):
    job = store.create(user_id=1, scenario="karaoke", command_id="cmd-1", params={"a": 1})
    store.complete(job.job_id, results=[{"video_id": "v1"}])

    loaded = {j.job_id: j for j in job_store.load_jobs()}
    assert loaded[job.job_id].status == "done"
    assert loaded[job.job_id].command_id == "cmd-1"
    assert loaded[job.job_id].params == {"a": 1}
    assert loaded[job.job_id].results == [{"video_id": "v1"}]


def test_resolve_or_reserve_returns_existing_for_active_command(store):
    def create():
        return store.create(user_id=1, command_id="cmd-1", params={"x": 1})

    first, created_first = job_store.resolve_or_reserve("cmd-1", create)
    second, created_second = job_store.resolve_or_reserve("cmd-1", create)

    assert created_first is True
    assert created_second is False
    assert first.job_id == second.job_id


def test_resolve_or_reserve_reissues_after_failure(store):
    def create():
        return store.create(user_id=1, command_id="cmd-1", params={"x": 1})

    first, _ = job_store.resolve_or_reserve("cmd-1", create)
    store.fail(first.job_id, "boom")

    second, created = job_store.resolve_or_reserve("cmd-1", create)

    assert created is True
    assert second.job_id != first.job_id


def test_resolve_or_reserve_is_atomic_under_concurrency(store):
    created_jobs = []
    barrier = threading.Barrier(8)

    def create():
        job = store.create(user_id=1, command_id="cmd-race", params={"x": 1})
        created_jobs.append(job.job_id)
        return job

    results = []

    def submit():
        barrier.wait()
        job, _ = job_store.resolve_or_reserve("cmd-race", create)
        results.append(job.job_id)

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(created_jobs) == 1
    assert set(results) == {created_jobs[0]}
    records = [j for j in job_store.load_jobs() if j.command_id == "cmd-race"]
    assert len(records) == 1


# ── restart reconcile ───────────────────────────────────────────────────────

def test_reconcile_reenqueues_or_fails_orphans(tmp_path, monkeypatch):
    import modules.api_worker as api_worker

    monkeypatch.setattr(job_store, "settings", _settings(output_dir=str(tmp_path)))

    # "Previous process": persisted one re-runnable job and one orphan.
    old_tracker = JobTracker(max_history=50)
    monkeypatch.setattr(job_store, "tracker", old_tracker)
    old_tracker.set_persist_hook(job_store.persist_job)
    rerunnable = old_tracker.create(
        user_id=1, command_id="cmd-1",
        params={"scenario": "karaoke", "source": {"kind": "minio_key", "value": "a/b.mp3"}},
    )
    old_tracker.update(rerunnable.job_id, current_phase="rendering")
    job_store.persist_job(old_tracker.get(rerunnable.job_id))
    orphan = old_tracker.create(user_id=1, scenario="spotify_download", params={})
    old_tracker.update(orphan.job_id, current_phase="downloading")
    job_store.persist_job(old_tracker.get(orphan.job_id))

    # "New process": fresh tracker + fresh queue.
    fresh_tracker = JobTracker(max_history=50)
    monkeypatch.setattr(job_store, "tracker", fresh_tracker)
    monkeypatch.setattr(api_worker, "tracker", fresh_tracker)
    monkeypatch.setattr(api_worker, "_queue", None)

    restored = api_worker.reconcile_persisted_jobs()

    assert restored == 1
    revived = fresh_tracker.get(rerunnable.job_id)
    assert revived is not None
    assert revived.provider_status == "queued"
    dead = fresh_tracker.get(orphan.job_id)
    assert dead is not None
    assert dead.provider_status == "failed"
    assert "orphaned by restart" in dead.error
    queued_item = api_worker.get_queue().get_nowait()
    assert queued_item["job_id"] == rerunnable.job_id
    assert queued_item["source"] == {"kind": "minio_key", "value": "a/b.mp3"}
