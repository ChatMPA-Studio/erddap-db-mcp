"""
Test directo de las tool functions (sin levantar el servidor MCP).
Prueba: list_coverage, list_datasets, get_dataset_info, get_data (live ERDDAP).
"""

import asyncio
import json
import sys


async def run_tests():
    from tools.data_access import (
        get_data,
        get_dataset_info,
        list_coverage,
        list_datasets,
    )

    passed = 0
    failed = 0

    def ok(name, result):
        nonlocal passed
        parsed = json.loads(result)
        print(f"\n[OK] {name}")
        print(json.dumps(parsed, indent=2)[:500])
        passed += 1

    def fail(name, exc):
        nonlocal failed
        print(f"\n[FAIL] {name}: {exc}")
        failed += 1

    # 1. list_coverage — espera store vacío o con datos parciales
    try:
        result = await list_coverage({})
        ok("list_coverage (all)", result)
    except Exception as e:
        fail("list_coverage (all)", e)

    # 2. list_coverage filtrado por variable
    try:
        result = await list_coverage({"variable": "chlorophyll"})
        ok("list_coverage (chlorophyll)", result)
    except Exception as e:
        fail("list_coverage (chlorophyll)", e)

    # 3. list_datasets
    try:
        result = await list_datasets({"variable": "chlorophyll"})
        ok("list_datasets (chlorophyll)", result)
    except Exception as e:
        fail("list_datasets (chlorophyll)", e)

    # 4. get_dataset_info — dataset default clorofila
    try:
        result = await get_dataset_info({"dataset_id": "erdMH1chla8day_R202SQ"})
        ok("get_dataset_info (chlorophyll default)", result)
    except Exception as e:
        fail("get_dataset_info (chlorophyll default)", e)

    # 5. get_dataset_info — dataset default SST
    try:
        result = await get_dataset_info({"dataset_id": "ncdcOisst21Agg_LonPM180"})
        ok("get_dataset_info (sst default)", result)
    except Exception as e:
        fail("get_dataset_info (sst default)", e)

    # 6. get_data — clorofila desde ERDDAP en vivo (query pequeña)
    try:
        result = await get_data({
            "variable": "chlorophyll",
            "bbox": [-92, -88, 22, 26],
            "date_range": ["2024-01-01", "2024-01-31"],
            "source": "erddap",
        })
        ok("get_data (chlorophyll, erddap live)", result)
    except Exception as e:
        fail("get_data (chlorophyll, erddap live)", e)

    # 7. get_data — SST desde ERDDAP en vivo
    try:
        result = await get_data({
            "variable": "sst",
            "bbox": [-92, -88, 22, 26],
            "date_range": ["2024-01-01", "2024-01-10"],
            "source": "erddap",
            "sst_var": "sst",
        })
        ok("get_data (sst, erddap live)", result)
    except Exception as e:
        fail("get_data (sst, erddap live)", e)

    # 8. get_data — SST anomaly
    try:
        result = await get_data({
            "variable": "sst",
            "bbox": [-92, -88, 22, 26],
            "date_range": ["2024-01-01", "2024-01-10"],
            "source": "erddap",
            "sst_var": "anom",
        })
        ok("get_data (sst anom, erddap live)", result)
    except Exception as e:
        fail("get_data (sst anom, erddap live)", e)

    print(f"\n{'='*40}")
    print(f"Resultados: {passed} OK / {failed} FAIL")
    return failed


if __name__ == "__main__":
    failures = asyncio.run(run_tests())
    sys.exit(1 if failures > 0 else 0)
