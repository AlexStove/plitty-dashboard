from modules.job_tracker import JobTracker


def test_job_tracker_completes_job_with_results():
    tracker = JobTracker(max_history=10)
    job = tracker.create(user_id=1, scenario="karaoke", total=2)

    tracker.update(job.job_id, progress=1, current_phase="rendering")
    completed = tracker.complete(job.job_id, results=[{"video_id": "abc"}])

    assert completed is not None
    assert completed.status == "done"
    assert completed.current_phase == "done"
    assert completed.percent == 100
    assert completed.results == [{"video_id": "abc"}]


def test_job_tracker_trims_finished_history():
    tracker = JobTracker(max_history=2)

    first = tracker.create(user_id=1)
    tracker.complete(first.job_id)
    second = tracker.create(user_id=1)
    tracker.complete(second.job_id)
    third = tracker.create(user_id=1)

    assert tracker.get(first.job_id) is None
    assert tracker.get(second.job_id) is not None
    assert tracker.get(third.job_id) is not None
