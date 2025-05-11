import asyncio
from os import environ
from shlex import quote
from subprocess import run
from typing import List

from snowflake_connector import QueryResult


def set_github_action_output(var_name, value):
    output_path = environ["GITHUB_OUTPUT"]

    output_line = f"{var_name}={value}"
    quoted_line = quote(output_line)
    quoted_path = quote(output_path)

    run(
        ["bash", "-c", f"echo {quoted_line} >> {quoted_path}"],
        check=True
    )


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
