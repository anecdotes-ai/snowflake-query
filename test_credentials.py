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
import subprocess
import sys

import pytest
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

    def test_key_takes_precedence_over_password(self):
        con = SnowflakeConnector("acct", "user", password="pw", private_key=_pem())
        assert con.private_key_der is not None

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
        ("", "empty"),
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
        """The delimiter is a uuid4 chosen after the value is fixed, so it cannot be guessed."""
        out = tmp_path / "gh_output"
        out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        set_github_action_output("queries_results", "ghadelimiter_x\nINJECTED=1")
        written = out.read_text()
        assert "\nINJECTED=1\n" in written
        # exactly one variable declared: opening line plus closing delimiter, nothing else
        assert written.count("queries_results<<") == 1

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
    declared = {line.split(":")[0].strip() for line in action.splitlines()
                if line.startswith("  snowflake_") or line.startswith("  queries:")}
    missing = sorted(name for name in declared if name not in readme)
    assert not missing, f"inputs declared in action.yml but absent from README: {missing}"
