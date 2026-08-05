# PR Proposal

## Ticket

UN-22647

## Title

refactor(backstop-mcp): resolve employment per person-organization pair

## Description

- Replace `detect_departed_employment`'s single collapsed verdict with an `EmploymentIndex` keyed
  by `(person_id, organization_id)`, so callers can ask whether someone is still at a *specific*
  organization instead of receiving one arbitrarily chosen departure.
- Resolve conflicting relationships to the same organization by latest effective date —
  `startDate`/`endDate` when present, `createdTimestamp` otherwise, ties breaking toward departed
  — which fixes the case where a current and a former relationship coexist for the same pair.
- Read the organization payload's mirror relationship types (`is employee of (mirror)`,
  `is a former employee of (mirror)`) through the same rule, via a second thin builder.
- Consolidate `departed.py` into `employment.py` and settle the naming: "employment" for the
  domain, "departure" only for the finding. `DepartedContactDetector` becomes
  `EmploymentIndexFactory`; `DepartureRules` becomes `EmploymentRules`; env var names unchanged.
- `get_person` now reports every departure it found (`departures: list[DepartedContactEcho]`)
  rather than a single `departed_detail`.
