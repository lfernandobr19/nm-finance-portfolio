from app.workers.arq_settings import ResearchWorkerSettings, WorkerSettings, redis_settings
from app.workers.jobs import job_exit_watch, job_ping, job_research


def test_redis_settings_parses_host_port_database():
    settings = redis_settings("redis://host:6380/3")
    assert settings.host == "host"
    assert settings.port == 6380
    assert settings.database == 3


def test_research_worker_is_isolated_from_trading_queue():
    assert ResearchWorkerSettings.queue_name == "arq:queue:research"
    assert ResearchWorkerSettings.max_jobs == 1
    assert WorkerSettings.max_jobs == 2
    assert ResearchWorkerSettings.queue_name != getattr(WorkerSettings, "queue_name", "arq:queue")
    # Context7/arq: no priority field. Isolation is a second Worker + queue.
    assert job_research not in WorkerSettings.functions
    assert job_research in ResearchWorkerSettings.functions
    assert job_exit_watch in WorkerSettings.functions
    assert job_ping in WorkerSettings.functions
    assert job_exit_watch not in ResearchWorkerSettings.functions
    assert ResearchWorkerSettings.job_timeout == 3600
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.health_check_interval == 60
    assert WorkerSettings.on_shutdown is not None
    from app.workers.arq_settings import on_shutdown

    assert WorkerSettings.on_shutdown is on_shutdown
