import asyncio
import os
import uuid
from typing import List

from snowflake_connector import QueryResult


def set_github_action_output(var_name, value):
    """
    Writes to $GITHUB_OUTPUT. Never through a shell.

    The previous implementation interpolated `value` into an `os.system` command, so Snowflake row
    content was evaluated by /bin/sh — a cell containing `$(...)` executed it, with the action's
    environment in reach. That environment now holds an unencrypted private key.

    `::set-output` was also disabled by GitHub in 2023, and the format string doubled its braces, so
    it emitted the literal text `{var_name}`. AN-19495 (b3b62cc) had already fixed all of this;
    AN-19858 (54cc002) reintroduced it. This restores the fix.

    The heredoc form is required because query results are JSON and may contain newlines, which the
    `name=value` form cannot represent. The delimiter is random per call so a value cannot close it.
    """
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        # Local/dry runs outside Actions: no output file to write to.
        print(f"{var_name}=<{len(str(value))} chars>")
        return
    delimiter = f"ghadelimiter_{uuid.uuid4()}"
    with open(github_output, "a", encoding="utf-8") as handle:
        handle.write(f"{var_name}<<{delimiter}\n{value}\n{delimiter}\n")


async def gather_all_results(query_result_list: List[QueryResult]) -> dict:
    """
    Iterates all QueryResults objects to run asynchronously,
    and gather their results when finish.
    Print whenever results available.

    Args:
        query_result_list (List[QueryResult]): List of QueryResults objects.

    Returns:
        str: json contains all of the results.
    """
    running_tasks = {asyncio.create_task(query_result.fetch_results(), name=query_result.query_id)
                                     for query_result in query_result_list}

    json_total_results = {}

    while len(running_tasks) != 0:
        done, running_tasks = await asyncio.wait(running_tasks, return_when=asyncio.FIRST_COMPLETED)

        for done_task in done:
            json_total_results[done_task.get_name()] = []
            print(f'### Query id {done_task.get_name()} results ###')

            for row in done_task.result():
                print(row)
                json_total_results[done_task.get_name()].append(str(row))

    return json_total_results
