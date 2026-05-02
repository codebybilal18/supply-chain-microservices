"""
Integration test configuration and fixtures.

These tests require a live Pub/Sub emulator. They are skipped automatically
unless the PUBSUB_EMULATOR_HOST environment variable is set OR the
--run-integration flag is passed to pytest.

Run locally:
    # Start the emulator (one-off):
    gcloud beta emulators pubsub start --project=local-project

    # In a second shell:
    PUBSUB_EMULATOR_HOST=localhost:8085 pytest tests/integration/ -v

Or via docker-compose:
    docker compose up pubsub-emulator pubsub-setup -d
    PUBSUB_EMULATOR_HOST=localhost:8085 pytest tests/integration/ -v
"""

import asyncio
import json
import os
import time
import uuid

import pytest


# ---------------------------------------------------------------------------
# CLI flag
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require a live Pub/Sub emulator.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests requiring Pub/Sub emulator",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    run_integration = config.getoption("--run-integration") or os.getenv(
        "PUBSUB_EMULATOR_HOST"
    )
    skip = pytest.mark.skip(
        reason="Set PUBSUB_EMULATOR_HOST or pass --run-integration to run integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            if not run_integration:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pubsub_emulator_host() -> str:
    """Return the Pub/Sub emulator host, or skip if not available."""
    host = os.getenv("PUBSUB_EMULATOR_HOST", "localhost:8085")
    return host


@pytest.fixture(scope="session")
def gcp_project_id() -> str:
    return os.getenv("GCP_PROJECT_ID", "local-project")


@pytest.fixture(scope="session")
def pubsub_publisher(pubsub_emulator_host, gcp_project_id):
    """Return a Pub/Sub PublisherClient pointed at the emulator."""
    os.environ["PUBSUB_EMULATOR_HOST"] = pubsub_emulator_host
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    yield publisher


@pytest.fixture(scope="session")
def pubsub_subscriber_client(pubsub_emulator_host):
    """Return a Pub/Sub SubscriberClient pointed at the emulator."""
    os.environ["PUBSUB_EMULATOR_HOST"] = pubsub_emulator_host
    from google.cloud import pubsub_v1

    client = pubsub_v1.SubscriberClient()
    yield client
    client.close()


def ensure_topic(publisher, project_id: str, topic_name: str) -> str:
    """Create topic if it doesn't already exist; return full topic path."""
    from google.api_core.exceptions import AlreadyExists

    topic_path = publisher.topic_path(project_id, topic_name)
    try:
        publisher.create_topic(request={"name": topic_path})
    except AlreadyExists:
        pass
    return topic_path


def ensure_subscription(
    subscriber_client,
    publisher,
    project_id: str,
    sub_name: str,
    topic_name: str,
    dlq_topic_name: str | None = None,
) -> str:
    """Create subscription if it doesn't already exist; return full path."""
    from google.api_core.exceptions import AlreadyExists
    from google.pubsub_v1.types import DeadLetterPolicy, Subscription

    sub_path = subscriber_client.subscription_path(project_id, sub_name)
    topic_path = publisher.topic_path(project_id, topic_name)

    req: dict = {
        "name": sub_path,
        "topic": topic_path,
        "ack_deadline_seconds": 30,
    }
    if dlq_topic_name:
        dlq_path = publisher.topic_path(project_id, dlq_topic_name)
        req["dead_letter_policy"] = DeadLetterPolicy(
            dead_letter_topic=dlq_path,
            max_delivery_attempts=5,
        )

    try:
        subscriber_client.create_subscription(request=req)
    except AlreadyExists:
        pass
    return sub_path


def pull_messages(
    subscriber_client,
    project_id: str,
    sub_name: str,
    expected_count: int = 1,
    timeout_seconds: int = 15,
) -> list[dict]:
    """Poll a subscription until expected_count messages are received."""
    sub_path = subscriber_client.subscription_path(project_id, sub_name)
    collected = []
    deadline = time.monotonic() + timeout_seconds

    while len(collected) < expected_count and time.monotonic() < deadline:
        try:
            response = subscriber_client.pull(
                request={"subscription": sub_path, "max_messages": 10},
                timeout=3,
            )
        except Exception:
            time.sleep(0.5)
            continue

        ack_ids = []
        for rm in response.received_messages:
            try:
                payload = json.loads(rm.message.data.decode())
                collected.append(payload)
                ack_ids.append(rm.ack_id)
            except Exception:
                pass

        if ack_ids:
            subscriber_client.acknowledge(
                request={"subscription": sub_path, "ack_ids": ack_ids}
            )

    return collected
