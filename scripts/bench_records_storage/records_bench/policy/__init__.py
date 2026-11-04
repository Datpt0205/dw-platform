"""record-access/01: the policy variants measured inside custom-objects/01's harness.

Each variant is A1 plus a declared replacement (ticket step 2): the record
policies, the reach ledger and its door, the `studio.acl_*` functions, the
actor boundaries and the assign and share stand-ins, and on the key axis the
`bigint` access key with the per-tenant numbers it is composed from. The seed,
the load, the simulated write path, the report and the container are the
harness's, unchanged (step 1). Nothing here is a D12 number: `--scale smoke` on
the dev machine picks a shape for tickets 02 and 03 to read; ticket 06 picks
again at D12 on the reference machine.

- `variants`: the variants and the DDL each renders.
- `inputs`: what the module adds after `seed(scale)` (step 3).
- `checks`: the self-checks of step 7.
- `measure`: the measurements of step 5.
- `run`: the cells, the winner of each axis and the combination.
"""
