# Tuple Reconciliation

The reconciliation module helps detect and fix drift between Django state and SpiceDB tuples.

## Usage

### As a Management Command

```bash
# Report mode: show expected tuple counts
python manage.py rebac_reconcile

# Fix mode: write tuples to SpiceDB
python manage.py rebac_reconcile --fix

# Dry run: report what would be done
python manage.py rebac_reconcile --dry-run

# Reconcile specific types only
python manage.py rebac_reconcile --type document --type folder --fix
```

### As a Celery Task

The `reconcile_tuples()` function is designed to work seamlessly with Celery:

```python
from celery import shared_task
from django_spicedb.sync.reconcile import reconcile_tuples

@shared_task
def reconcile_permissions():
    """Periodic task to reconcile ReBAC tuples."""
    results = reconcile_tuples(fix=True)

    # Return types that had tuples to write
    return [r.type_name for r in results if r.to_write > 0]

@shared_task
def reconcile_specific_types():
    """Reconcile only specific types."""
    results = reconcile_tuples(fix=True, types=['document', 'folder'])
    return len([r for r in results if r.fixed])
```

### As a Standalone Function

```python
from django_spicedb.sync.reconcile import reconcile_type, reconcile_all

# Reconcile a single type
result = reconcile_type('document', fix=True)
print(f"Expected: {result.expected}, To write: {result.to_write}")

# Reconcile all types
results = reconcile_all(fix=True)
for result in results:
    if result.to_write > 0:
        print(f"{result.type_name}: {result.to_write} tuples to write")
```

## How It Works

1. **Compute Expected Tuples**: For each type, the reconciler queries all Django model instances and computes the tuples that should exist based on:
   - FK bindings (via `_gather_tuple_writes`)
   - M2M bindings (via `_gather_tuple_writes`)
   - Through-table bindings (via `generate_through_tuples`)

2. **Report Counts**: The reconciler counts expected tuples and reports them.

3. **Fix Mode**: When `fix=True`, the reconciler writes all expected tuples to SpiceDB.

## Limitations

### Stale Tuple Detection

The current implementation **cannot detect stale tuples** (tuples in SpiceDB that no longer correspond to Django state). This would require a `read_tuples()` method on the `RebacAdapter` protocol to:

1. Read all tuples for a type from SpiceDB
2. Compare them against expected tuples from Django
3. Identify and delete tuples that exist in SpiceDB but not in Django

The `stale` field in `ReconcileResult` will always be `0` until this feature is implemented.

### Performance Considerations

- The reconciler iterates over **all instances** of each model, which can be slow for large datasets
- For production use, consider:
  - Running reconciliation during off-peak hours
  - Using Celery to run it as an asynchronous background task
  - Reconciling specific types rather than all types at once
  - Implementing batch processing with pagination for very large datasets

## Example Output

```
FIX MODE: Tuples will be written to SpiceDB

Reconciling tuples...

==================================================
TYPE        EXPECTED   TO WRITE      STALE     FIXED
==================================================
user              25         25          0      True
document         150        150          0      True
folder            42         42          0      True
==================================================
TOTAL            217        217          0      True
==================================================

Successfully wrote 217 tuples to SpiceDB

Note: Stale tuple detection requires a read_tuples() adapter method (not yet implemented).
```
