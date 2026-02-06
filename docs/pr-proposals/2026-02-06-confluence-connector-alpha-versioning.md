# PR Proposal

## Title
chore(confluence-connector): switch to 2.0.0-alpha versioning

## Description
- Switch confluence-connector prerelease type from `beta` to `alpha` in release-please config
- Seed version at `2.0.0-alpha.0` across manifest, package.json, Chart.yaml, and values.yaml
- Update GitOps QA targetRevision to `confluence-connector@2.0.0-alpha.1`
- First release-please run on main will create the `2.0.0-alpha.1` release
