import csv
import json

import pytest

from awsce import export, html


def _account(service="Amazon EC2", usage="BoxUsage", account_id="111111111111"):
    return {
        "profile": "dev",
        "account_id": account_id,
        "start": "2026-01-01",
        "end": "2026-03-01",
        "total": 12.5,
        "months": {"2026-01": 5.0, "2026-02": 7.5},
        "services": [
            {
                "service": service,
                "total": 12.5,
                "usage_types": [
                    {"usage_type": usage, "cost": 12.5, "quantity": 100.0, "unit": "Hrs"},
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("name", "fmt"), [("a.csv", "csv"), ("a.JSON", "json"), ("a.html", "html")]
)
def test_output_format(tmp_path, name, fmt):
    assert export.output_format(tmp_path / name) == fmt


@pytest.mark.parametrize("name", ["a.xlsx", "report"])
def test_output_format_rejects_unknown(tmp_path, name):
    with pytest.raises(export.ExportError):
        export.output_format(tmp_path / name)


def test_csv_blocks_formulas_but_keeps_numbers(tmp_path):
    path = tmp_path / "out.csv"
    export.write_csv(
        path, ["a", "b", "c", "d", "e"], [["=HYPERLINK(1)", "-5.25", -3.5, "-", "@sum"]]
    )
    rows = list(csv.reader(path.open()))
    assert rows[1] == ["'=HYPERLINK(1)", "-5.25", "-3.5", "-", "'@sum"]


def test_account_rows():
    header, rows = export.account_rows([_account()])
    assert header[0] == "profile"
    assert rows == [["dev", "111111111111", "Amazon EC2", "BoxUsage", 100.0, "Hrs", 12.5]]


def test_json_export(tmp_path):
    path = tmp_path / "out.json"
    export.write_json(path, [_account()])
    assert json.loads(path.read_text())[0]["total"] == 12.5


def test_html_escapes_names_from_aws():
    evil = "</script><script>alert(1)</script>"
    page = html.costs_report([_account(service=evil, usage="<b>x</b>")])
    assert "<script>alert(1)</script>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    # Data for charts is JSON with HTML-unsafe characters escaped.
    assert "\\u003c/script\\u003e" in page
    assert 'integrity="sha384-' in page
    assert "data:image/svg+xml;base64," in page
    assert "$12.50" in page
    assert "Cost by month" in page


def test_category_html():
    report = {
        "category": "Team",
        "account_id": "1",
        "profile": "dev",
        "start": "2026-01-01",
        "end": "2026-02-01",
        "total": 10.0,
        "first_seen": {"web": "2025-12"},
        "values": [
            {
                "value": "web",
                "total": 10.0,
                "services": [
                    {"service": "Amazon S3", "cost": 10.0, "quantity": 1.0, "unit": "GB-Mo"},
                ],
            }
        ],
    }
    page = html.category_report(report)
    assert "Cost category report: Team" in page
    assert "2025-12" in page
    header, rows = export.category_rows(report)
    assert rows == [["Team", "web", "2025-12", "Amazon S3", 1.0, "GB-Mo", 10.0]]


def test_money_formatting():
    assert html._money(1234.5) == "$1,234.50"
    assert html._money(-3) == "-$3.00"
