# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-16

First public release.

### Added

- `awsce costs`: costs by service and usage type, for one or more profiles, with `accounts`, `services` and `summary` views.
- `awsce services`: services with cost or usage in a period.
- `awsce cost-category`: costs grouped by an AWS Cost Category, with the first month each value had cost.
- `awsce optimize rightsizing`: AWS Compute Optimizer recommendations for EC2, Auto Scaling, EBS, Lambda, RDS and ECS on Fargate, per profile, per region, or across an AWS Organization.
- `awsce optimize hub`: AWS Cost Optimization Hub recommendations.
- Export to CSV, JSON and HTML.
- Local cache, to avoid paying for repeated Cost Explorer requests.
