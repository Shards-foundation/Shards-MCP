"""Cross-session task/effect race tests; uses only psql and Python stdlib.

Run after tenancy_contract.sql against disposable PostgreSQL 16/17.
The test waits for a *real* server-side row-lock wait (pg_stat_activity),
not a guessed sleep, then validates both winner orders.
"""
from __future__ import annotations

import os
import select
import subprocess
import time

ORG = "00000000-0000-4000-8000-000000000001"
PSQL = ["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"]
TIMEOUT = 12


def sql(statement: str) -> str:
    completed = subprocess.run(
        [*PSQL, "-c", statement],
        capture_output=True, text=True, timeout=TIMEOUT, check=True,
    )
    return completed.stdout.strip()


def fixture() -> None:
    sql(f"""
        BEGIN;
        SET ROLE shards_v2_runtime;
        SELECT set_config('shards.org_id','{ORG}',true);
        INSERT INTO shards_v2.tasks
          (org_id,task_id,creator_id,worker_id,input_json,payload_sha256)
        VALUES
          ('{ORG}','task_race_close','agt_a_creator','agt_a_worker',
            '{{"race":"close-first"}}',sha256(convert_to('{{"race":"close-first"}}','UTF8'))),
          ('{ORG}','task_race_effect','agt_a_creator','agt_a_worker',
            '{{"race":"effect-first"}}',sha256(convert_to('{{"race":"effect-first"}}','UTF8')));
        UPDATE shards_v2.tasks SET state='running'
          WHERE task_id IN ('task_race_close','task_race_effect');
        COMMIT;
    """)


def held_session(statement: str, marker: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        PSQL, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    assert process.stdin and process.stdout
    process.stdin.write(statement.strip() + "\n\\echo " + marker + "\n")
    process.stdin.flush()
    # Do not mix select() on the OS fd with buffered TextIOWrapper.readline():
    # readline may prefetch the marker while select reports no more fd bytes.
    fd = process.stdout.fileno()
    received = b""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            chunk = os.read(fd, 4096)
            received += chunk
            if marker.encode("ascii") in received.splitlines():
                return process
            if not chunk and process.poll() is not None:
                raise AssertionError(f"session exited before lock marker {marker}")
        elif process.poll() is not None:
            raise AssertionError(f"session exited before lock marker {marker}")
    process.kill()
    raise AssertionError(f"session did not acquire lock for {marker}")


def blocked_attempt(app_name: str, body: str) -> subprocess.Popen[str]:
    env = dict(os.environ, PGAPPNAME=app_name)
    process = subprocess.Popen(
        [*PSQL, "-c", body],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.communicate()
            raise AssertionError(
                f"{app_name} completed before holding session committed: {output}"
            )
        states = sql(
            "SELECT COALESCE(wait_event_type,'') FROM pg_stat_activity "
            f"WHERE application_name='{app_name}' AND state='active';"
        )
        if "Lock" in states.splitlines():
            return process
        time.sleep(0.1)
    process.kill()
    raise AssertionError(f"{app_name} never blocked on a PostgreSQL lock")


def release(session: subprocess.Popen[str]) -> None:
    assert session.stdin
    session.stdin.write("COMMIT;\n\\q\n")
    session.stdin.flush()
    rc = session.wait(timeout=TIMEOUT)
    if rc:
        assert session.stderr
        raise AssertionError(f"held session commit failed: {session.stderr.read()}")


def verify_attempt(process: subprocess.Popen[str]) -> None:
    out, err = process.communicate(timeout=TIMEOUT)
    if process.returncode:
        raise AssertionError(f"racing session failed: {out}\n{err}")


def run() -> None:
    fixture()

    # Case 1: task close holds parent lock; effect INSERT waits, then must
    # fail after parent transitions to failed. No effect may remain.
    close = held_session(f"""
        BEGIN;
        SET ROLE shards_v2_runtime;
        SELECT set_config('shards.org_id','{ORG}',true);
        UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_race_close';
    """, "TASK_CLOSED_IN_TRANSACTION")
    try:
        effect = blocked_attempt("shards_race_effect_after_close", f"""
            BEGIN;
            SET ROLE shards_v2_runtime;
            SELECT set_config('shards.org_id','{ORG}',true);
            DO $attack$
            BEGIN
              BEGIN
                INSERT INTO shards_v2.effect_outbox
                  (org_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref)
                VALUES ('{ORG}','task_race_close','agt_a_worker','github-pr',
                    'race-close-first',decode(repeat('ac',32),'hex'),'vault://ci/no-secret');
                RAISE EXCEPTION 'FAIL: effect inserted after task closed';
              EXCEPTION WHEN check_violation THEN NULL;
              END;
            END $attack$;
            COMMIT;
        """)
    finally:
        release(close)
    verify_attempt(effect)
    closed = sql(
        f"SELECT state FROM shards_v2.tasks WHERE org_id='{ORG}' "
        "AND task_id='task_race_close'"
    )
    count = sql(
        f"SELECT count(*) FROM shards_v2.effect_outbox WHERE org_id='{ORG}' "
        "AND task_id='task_race_close'"
    )
    assert closed == "failed" and count == "0", (closed, count)

    # Case 2: effect INSERT first locks the parent. The task close waits,
    # then is denied because the newly committed outbox is still pending.
    init_effect = held_session(f"""
        BEGIN;
        SET ROLE shards_v2_runtime;
        SELECT set_config('shards.org_id','{ORG}',true);
        INSERT INTO shards_v2.effect_outbox
          (org_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref)
        VALUES ('{ORG}','task_race_effect','agt_a_worker','github-pr',
          'race-effect-first',decode(repeat('ba',32),'hex'),'vault://ci/no-secret');
    """, "EFFECT_REGISTERED_IN_TRANSACTION")
    try:
        close_attempt = blocked_attempt("shards_race_close_after_effect", f"""
            BEGIN;
            SET ROLE shards_v2_runtime;
            SELECT set_config('shards.org_id','{ORG}',true);
            DO $attack$
            BEGIN
              BEGIN
                UPDATE shards_v2.tasks SET state='failed'
                  WHERE task_id='task_race_effect';
                RAISE EXCEPTION 'FAIL: task closed over pending effect';
              EXCEPTION WHEN check_violation THEN NULL;
              END;
            END $attack$;
            COMMIT;
        """)
    finally:
        release(init_effect)
    verify_attempt(close_attempt)
    task = sql(
        f"SELECT state FROM shards_v2.tasks WHERE org_id='{ORG}' "
        "AND task_id='task_race_effect'"
    )
    effect = sql(
        f"SELECT state FROM shards_v2.effect_outbox WHERE org_id='{ORG}' "
        "AND task_id='task_race_effect'"
    )
    assert task == "running" and effect == "pending", (task, effect)
    print("TASK_EFFECT_RACE_CONTRACT_PASS: both lock orders denied unsafe operations")


if __name__ == "__main__":
    run()
