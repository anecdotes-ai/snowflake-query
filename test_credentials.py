"""
Covers the credential seam and the output writer — the two things that can leak a secret or
silently stop working, and the only parts of this action testable without Snowflake.

Runs inside the image build (see Dockerfile), not on this repo's CI: GitHub Actions is disabled at
the repo level, so a workflow here would never fire. A `docker` action builds its image on the
runner inside the *consumer's* workflow, where Actions is enabled — so these execute on every
invocation, before any query reaches Snowflake.
"""
import json
import os
import re
import subprocess
import sys

import pytest
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from snowflake_connector import SnowflakeConnector
from utils import set_github_action_output


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class _FakeConnection:
    """Stands in for a live Snowflake connection so credential routing is testable offline."""

    def close(self):
        pass


def _parse_github_output(text: str) -> dict:
    """
    Parses $GITHUB_OUTPUT the way the runner does, so a test can assert on the variables that
    actually result rather than on substrings. A heredoc break-out shows up here as an extra key —
    substring assertions cannot see it, which is how an earlier version of the delimiter test
    passed against an output that genuinely broke out.
    """
    variables, lines, index = {}, text.splitlines(), 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, delimiter = line.split("<<", 1)
            index += 1
            body = []
            while index < len(lines) and lines[index] != delimiter:
                body.append(lines[index])
                index += 1
            variables[name] = "\n".join(body)
        elif "=" in line:
            name, value = line.split("=", 1)
            variables[name] = value
        index += 1
    return variables


class TestCredentialSelection:
    def test_neither_credential_is_rejected_before_connecting(self):
        """Fail on the caller's mistake, not later inside the driver with a vaguer message."""
        with pytest.raises(ValueError, match="no credentials supplied"):
            SnowflakeConnector("acct", "user")

    def test_password_only_forwards_exactly_as_before(self):
        """Three consumers pin @v1.2 and pass only a password. They must not change behaviour."""
        con = SnowflakeConnector("acct", "user", "pw")
        assert con.private_key_der is None
        assert con.password == "pw"

    def test_key_takes_precedence_over_password_at_connect_time(self, monkeypatch):
        """
        Asserted on what reaches the driver, not on what __init__ stored. An earlier version of
        this test inspected `private_key_der` only, and still passed with the whole `__enter__`
        branch disabled — it gated the PR's headline behaviour not at all.
        """
        captured = {}

        def fake_connect(**kwargs):
            captured.update(kwargs)
            return _FakeConnection()

        monkeypatch.setattr(snowflake.connector, "connect", fake_connect)
        with SnowflakeConnector("acct", "user", password="pw", private_key=_pem()):
            pass
        assert "private_key" in captured
        assert "password" not in captured, "password reached the driver despite a key being supplied"

    def test_password_only_reaches_the_driver_unchanged(self, monkeypatch):
        """The three @v1.2 callers pass only a password; their kwargs must not drift."""
        captured = {}

        def fake_connect(**kwargs):
            captured.update(kwargs)
            return _FakeConnection()

        monkeypatch.setattr(snowflake.connector, "connect", fake_connect)
        with SnowflakeConnector("acct", "user", "pw"):
            pass
        assert captured == {"user": "user", "password": "pw", "account": "acct"}

    def test_single_line_and_multiline_pem_are_equivalent(self):
        """
        The single-line form is the one that matters: that is how a PEM arrives from a GitHub
        secret. If only the multiline form parsed, every real caller would fail.
        """
        pem = _pem()
        multiline = SnowflakeConnector("a", "u", private_key=pem).private_key_der
        escaped = SnowflakeConnector("a", "u", private_key=pem.replace("\n", "\\n")).private_key_der
        assert multiline == escaped

    @pytest.mark.parametrize("bad,label", [
        ("not a pem at all", "garbage"),
        ("-----BEGIN PRIVATE KEY-----\n-----END PRIVATE KEY-----", "armor only"),
    ])
    def test_unusable_key_is_rejected_naming_the_input(self, bad, label):
        with pytest.raises(ValueError) as exc:
            SnowflakeConnector("acct", "user", private_key=bad or None, password=None)
        assert "snowflake_private_key" in str(exc.value), label

    def test_parse_failure_does_not_echo_key_material(self):
        """A truncated real key must not surface its own bytes in the error text."""
        pem = _pem()
        truncated = pem[: len(pem) // 2]
        with pytest.raises(ValueError) as exc:
            SnowflakeConnector("acct", "user", private_key=truncated)
        body = truncated.replace("-----BEGIN PRIVATE KEY-----\n", "").strip()
        assert body[:40] not in str(exc.value)


class TestOutputWriter:
    def test_row_content_is_never_evaluated_by_a_shell(self, tmp_path, monkeypatch):
        """
        The regression this file exists for. `set_github_action_output` once interpolated query
        results into os.system, so a cell containing $(...) executed — with the private key in the
        environment. json.dumps does not defuse it: it escapes quotes and backslashes, not `$`.
        """
        marker = tmp_path / "pwned"
        out = tmp_path / "gh_output"
        out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        payload = json.dumps({"q1": [[f"$(touch {marker})"]]})

        set_github_action_output("queries_results", payload)

        assert not marker.exists(), "row content reached a shell"
        assert payload in out.read_text()

    def test_multiline_value_round_trips(self, tmp_path, monkeypatch):
        """Results are JSON and may contain newlines; `name=value` cannot represent them."""
        out = tmp_path / "gh_output"
        out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        set_github_action_output("queries_results", "line1\nline2")
        written = out.read_text()
        assert "line1\nline2" in written
        assert written.count("ghadelimiter_") == 2

    def test_value_shaped_like_the_delimiter_cannot_close_it(self, tmp_path, monkeypatch):
        """
        The delimiter is a uuid4 chosen after the value is fixed, so a value cannot guess it and
        declare a second variable. Asserted by parsing the result: a break-out produces an extra
        key, which substring checks cannot detect.
        """
        out = tmp_path / "gh_output"
        out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        payload = "ghadelimiter_x\nINJECTED=1"

        set_github_action_output("queries_results", payload)

        variables = _parse_github_output(out.read_text())
        assert list(variables) == ["queries_results"], f"value declared extra variables: {variables}"
        assert variables["queries_results"] == payload


    def test_missing_github_output_does_not_crash(self, monkeypatch, capsys):
        """load_dotenv() means local runs are supported; they have no GITHUB_OUTPUT."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        set_github_action_output("queries_results", "anything")
        assert "queries_results" in capsys.readouterr().out

    def test_unwritable_output_warns_instead_of_failing_the_step(self, tmp_path, monkeypatch, capsys):
        """
        runner-images#10915: the image runs as uid 1000, the runner owns GITHUB_OUTPUT as uid 1001.
        By this point the queries have already run — including CREATE OR REPLACE TABLE against prod
        in revert-from-backup — so raising here would fail the step after the side effects landed.
        """
        out = tmp_path / "gh_output"
        out.write_text("")
        out.chmod(0o400)
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        if os.access(out, os.W_OK):  # running as root, e.g. in the image build
            pytest.skip("cannot simulate an unwritable file as root")

        set_github_action_output("queries_results", "value")

        assert "::warning::" in capsys.readouterr().out


def test_action_yml_and_readme_agree_on_inputs():
    """
    This action is public and listed on GitHub Marketplace, and the Marketplace page renders the
    README — action.yml is not a rendered surface. An input documented only in action.yml is
    invisible to the people who need to migrate off passwords before Snowflake removes them.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    action = open(os.path.join(here, "action.yml"), encoding="utf-8").read()
    readme = open(os.path.join(here, "README.md"), encoding="utf-8").read()
    declared = set(re.findall(r"^\s{2,}(snowflake_\w+|queries):", action, re.M))
    missing = sorted(name for name in declared if name not in readme)
    assert not missing, f"inputs declared in action.yml but absent from README: {missing}"
