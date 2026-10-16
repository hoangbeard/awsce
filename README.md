# awsce

> Check, summarize and analyze your AWS costs from the command line.

[![ci](https://github.com/hoangbeard/awsce/actions/workflows/ci.yml/badge.svg)](https://github.com/hoangbeard/awsce/actions/workflows/ci.yml)
[![security](https://github.com/hoangbeard/awsce/actions/workflows/security.yml/badge.svg)](https://github.com/hoangbeard/awsce/actions/workflows/security.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/hoangbeard/awsce/badge)](https://scorecard.dev/viewer/?uri=github.com/hoangbeard/awsce)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why

The AWS console is slow when you only want a quick answer:

- What did we spend this month, and on which services?
- Which usage type inside EC2 costs the most?
- How do five accounts compare, side by side?
- Where can we save money right now?

`awsce` answers these from your terminal, using the AWS credentials you already have. When you need to share the answer, it exports CSV, JSON or a self-contained HTML report.

## Install

Requires Python 3.10 or newer.

```bash
pipx install awsce        # or: pip install awsce
awsce --version
```

From source:

```bash
git clone https://github.com/hoangbeard/awsce.git
cd awsce
pip install -e .
```

## Quick start

```bash
# This month so far, for your default profile
awsce costs

# Last month, saved as an HTML report
awsce costs --start 2026-09-01 --end 2026-10-01 -o september.html

# Compare several accounts, grouped by service
awsce costs -p dev -p staging -p prod --view services

# Where can we save money?
awsce optimize rightsizing -r us-east-1 -r eu-west-1
awsce optimize hub
```

## Commands

| Command | What it does |
|---|---|
| `awsce costs` | Costs by service and usage type, for one or more accounts |
| `awsce services` | AWS services that had cost or usage in a period |
| `awsce cost-category NAME` | Costs grouped by an [AWS Cost Category](https://docs.aws.amazon.com/cost-management/latest/userguide/manage-cost-categories.html), then by service |
| `awsce optimize rightsizing` | Rightsizing recommendations from AWS Compute Optimizer |
| `awsce optimize hub` | Savings recommendations from AWS Cost Optimization Hub |
| `awsce cache list` / `clear` | Look at or remove cached results |

Run any command with `--help` to see all options.

### Periods

`--start` is the first day. `--end` is the day **after** the last day, the same way Cost Explorer works. So `--start 2026-09-01 --end 2026-10-01` is all of September.

With no dates, `awsce` shows the current month so far. On the 1st of a month, it shows last month instead.

### Many accounts

Use one profile per account:

```bash
awsce costs -p dev -p prod              # chosen profiles
awsce costs --all-profiles              # every profile in ~/.aws/config
```

Then pick how to see them with `--view`:

| View | Shows |
|---|---|
| `accounts` (default) | Each account on its own |
| `services` | Each service, with what every account spends on it |
| `summary` | Each usage type across all accounts, with total usage and average unit price |

If one profile fails, for example an expired SSO session, `awsce` warns you and goes on with the rest.

If you use AWS Organizations, you can also run `awsce costs` once with the management account. Cost Explorer there already includes every member account.

### Small amounts

Rows under $0.01 are hidden by default to keep the output short. Totals always include them. Add `--detail` to see every row. Credits and refunds (negative amounts) are always shown.

### Export

Add `-o FILE`. The format follows the extension:

| Extension | Content |
|---|---|
| `.csv` | One row per usage type, ready for a spreadsheet |
| `.json` | The full data, for scripts |
| `.html` | A report with charts that you can open in any browser or send by email (`costs` and `cost-category` only) |

### Savings recommendations

```bash
# Compute Optimizer: EC2, Auto Scaling, EBS, Lambda, RDS, ECS on Fargate
awsce optimize rightsizing -r us-east-1 --type ec2 --type ebs --min-savings 10

# Every member account, from the management account
awsce optimize rightsizing -p management --organization

# Cost Optimization Hub: rightsizing, Savings Plans, Reserved Instances and more
awsce optimize hub --type Ec2Instance --limit 20
```

Both services must be turned on in your account first:
[Compute Optimizer](https://docs.aws.amazon.com/compute-optimizer/latest/ug/getting-started.html) and
[Cost Optimization Hub](https://docs.aws.amazon.com/cost-management/latest/userguide/coh-getting-started.html).

## Cost and caching

Cost Explorer charges **$0.01 for each API request**. To keep this low, `awsce` caches results on your machine:

| Data | Cached for |
|---|---|
| Costs and cost categories | 24 hours |
| Recommendations | 4 hours |

Use `--refresh` to skip the cache, or `--cache-hours` to change how long it lasts. The cache lives in `~/.cache/awsce` (or `$AWSCE_CACHE_DIR`).

## Permissions

`awsce` only reads. A minimal IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Costs",
      "Effect": "Allow",
      "Action": ["ce:GetCostAndUsage", "ce:GetDimensionValues"],
      "Resource": "*"
    },
    {
      "Sid": "Recommendations",
      "Effect": "Allow",
      "Action": [
        "compute-optimizer:GetEC2InstanceRecommendations",
        "compute-optimizer:GetAutoScalingGroupRecommendations",
        "compute-optimizer:GetEBSVolumeRecommendations",
        "compute-optimizer:GetLambdaFunctionRecommendations",
        "compute-optimizer:GetRDSDatabaseRecommendations",
        "compute-optimizer:GetECSServiceRecommendations",
        "cost-optimization-hub:ListRecommendations",
        "organizations:ListAccounts"
      ],
      "Resource": "*"
    }
  ]
}
```

Compute Optimizer also needs read access to the resources it reports on. The AWS managed policy `ComputeOptimizerReadOnlyAccess` covers this.

## Security notes

- `awsce` never writes to your AWS account.
- Credentials come from the normal AWS chain (profiles, SSO, environment variables). `awsce` never stores them, and error output never prints them.
- Cache files hold account IDs and cost data. They are readable only by you (mode `600`).
- HTML reports escape every name that comes from AWS. CSV exports guard against spreadsheet formula injection.
- HTML reports load Chart.js from a CDN, pinned with a Subresource Integrity hash.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

pytest              # tests use botocore Stubber, no AWS account needed
ruff check . && ruff format --check .
mypy src
```

## License

[MIT](LICENSE) © Pham Huy Hoang (HoangBeard)
