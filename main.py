import os
import asyncio
import json

from dotenv import load_dotenv

import utils
from snowflake_connector import SnowflakeConnector

def main():
    load_dotenv() # only on local run
    queries_list = os.environ['INPUT_QUERIES'].split(';')
    sync = os.environ.get("INPUT_SYNC", False)
    warehouse = os.environ['INPUT_SNOWFLAKE_WAREHOUSE']
    snowflake_account = os.environ['INPUT_SNOWFLAKE_ACCOUNT']
    snowflake_username = os.environ['INPUT_SNOWFLAKE_USERNAME']
    snowflake_password = os.environ['INPUT_SNOWFLAKE_PASSWORD']
    snowflake_role = os.environ.get('INPUT_SNOWFLAKE_ROLE', '')
    
    with SnowflakeConnector(snowflake_account, snowflake_username, snowflake_password) as con:
        try:
            if snowflake_role != '':
                con.set_user_role(snowflake_role)
        except:
            pass
        
        con.set_db_warehouse(warehouse)

        query_results = []
        for query in queries_list:
            query_result = con.query(query)
            query_results.append(query_result)
            print("### Running query ###")
            print(f"[!] Query id - {query_result.query_id}")
            print(f"[!] Running query ### - {query}")

        if not sync:
            json_results = asyncio.run(utils.gather_all_results(query_results))
        else:
            json_results = utils.gather_all_results_sync(query_results)

    utils.set_github_action_output('queries_results', json.dumps(json_results))
    
if __name__ == '__main__':
    main()