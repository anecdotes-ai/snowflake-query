import asyncio
from os import system
from typing import List

from snowflake_connector import QueryResult


def set_github_action_output(var_name, value):
    system(f'echo "::set-output name={{var_name}}::"{value}""')


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
