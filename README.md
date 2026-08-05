# Snowflake-query

![last tag](https://img.shields.io/github/v/tag/anecdotes-ai/snowflake-query?color=brightgreen&label=release&logo=github)
![Sanity Workflow](https://github.com/anecdotes-ai/snowflake-query/actions/workflows/sanity.yml/badge.svg?branch=master)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This github action runs SQL queries list in Snowflake DB, which its access configuration is defined in the workflow.

## Inputs

- `snowflake_account` - Account name for Snowflake DB. Your account name is the full/entire string to the left of snowflakecomputing.com.
- `snowflake_warehouse` - Set the warehouse context for the queries.
- `snowflake_username` - The Snowflake user to authenticate as.
- `snowflake_private_key` - Private key for key-pair authentication. **Preferred.** Snowflake is
  removing password authentication for service users, so new callers should use this.
  - Must be an **unencrypted PKCS#8** key — the contents of an `rsa_key.p8`. Passphrase-protected
    keys are not supported.
  - Accepts either real newlines or a single line with literal `\n` escapes, so it works whether
    the secret was stored multi-line or flattened.
  - Generate with:
    ```
    openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
    openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
    ```
    then register the public half on the user: `ALTER USER <NAME> SET RSA_PUBLIC_KEY='<pub>'`.
- `snowflake_password` - Password for your DB. Still supported, but **deprecated by Snowflake for
  service users**. Supply this or `snowflake_private_key`; if both are given, the key is used and
  the password is ignored.
  - It's recommended to use [Github's Secrets](https://docs.github.com/en/actions/reference/encrypted-secrets) for credential arguments.
- `snowflake_role` (optional) - Set a role for the user.
- `queries` - SQL queries to execute **asynchronously and independently**.
  - May contain multiple queries, seperated by ';'
  - Don't use ';' with the last query.
  - If you need to contain a single-quote in one or more queries, escape it with another single-quote.

## Output

`queries_results` - Json string contains the results from all queires executed. For example, for the query `SELECT CURRENT_VERSION()`, we'll get - `{'019ca1a1-0000-43ef-0000-15ed05cb1c4e': ['('5.20.1',)']}`.

It may be accessed in following steps by `${{steps.run_queries.outputs.queries_output}}`. See [this](https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#tojson) guide for more github's action expressions examples.

## Usage

### Run multiple queries in one job

```yaml
steps:
  - name: Run queries
    uses: anecdotes-ai/snowflake-query@v1
    id: run_queries
    with:
        snowflake_account: ${{ secrets.SNOWFLAKE_ACCOUNT }}
        snowflake_warehouse: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
        snowflake_username: ${{ secrets.SNOWFLAKE_USER }}
        # key-pair auth — preferred; swap snowflake_password for this
        snowflake_private_key: ${{ secrets.SNOWFLAKE_PRIVATE_KEY }}
        queries: 'call system$wait(5);
                  select CURRENT_VERSION();
                  select * from "<TABLE_NAME>" where <column_name>=''<value>'''
        # single quote is escaped with another single quote

    - name: Version Query Validation
        run: |
          ${{contains(steps.run_queries.outputs.queries_output, '5.20.1')}}
```

### Run multiple queries as a job-matrix

```yaml
strategy:
  matrix: 
    table: ['TABLE1', 'TABLE2', 'TABLE3',
            'TABLE4', 'TABLE5']
steps:
  - name: Run Delete Queries
    uses: anecdotes-ai/snowflake-query@v1
    id: run_delete_queries
    with:
      snowflake_account: ${{ secrets.SNOWFLAKE_ACCOUNT }}
      snowflake_warehouse: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
      snowflake_username: ${{ secrets.SNOWFLAKE_USER }}
      snowflake_password: ${{ secrets.SNOWFLAKE_PASSWORD }}
      queries: 'DELETE FROM  "${{matrix.table}}"'
```

