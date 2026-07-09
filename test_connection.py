"""
Test de conexión a NOAA CoastWatch ERDDAP.
Prueba los dos datasets default con una query pequeña.
"""

from erddapy import ERDDAP

SERVER = "https://coastwatch.pfeg.noaa.gov/erddap"

# bbox Golfo de México (más pequeño = descarga más rápida para prueba)
BBOX = {"lon_min": -92, "lon_max": -88, "lat_min": 22, "lat_max": 26}
DATE_START = "2024-01-01"
DATE_END = "2024-01-31"


def test_chlorophyll():
    print("\n--- Probando clorofila (erdMH1chla8day_R202SQ) ---")
    e = ERDDAP(server=SERVER, protocol="griddap")
    e.dataset_id = "erdMH1chla8day_R202SQ"
    e.griddap_initialize()

    e.constraints["time>="] = DATE_START
    e.constraints["time<="] = DATE_END
    e.constraints["latitude>="] = BBOX["lat_min"]
    e.constraints["latitude<="] = BBOX["lat_max"]
    e.constraints["longitude>="] = BBOX["lon_min"]
    e.constraints["longitude<="] = BBOX["lon_max"]

    print("Descargando...")
    ds = e.to_xarray()
    print(f"OK — shape: {ds[list(ds.data_vars)[0]].shape}")
    print(f"   variable: {list(ds.data_vars)}")
    print(f"   tiempo:   {ds.time.values[0]} -> {ds.time.values[-1]}")
    print(f"   lat:      {float(ds.latitude.min()):.2f} -> {float(ds.latitude.max()):.2f}")
    print(f"   lon:      {float(ds.longitude.min()):.2f} -> {float(ds.longitude.max()):.2f}")
    return ds


def test_sst():
    print("\n--- Probando SST (ncdcOisst21Agg_LonPM180) ---")
    e = ERDDAP(server=SERVER, protocol="griddap")
    e.dataset_id = "ncdcOisst21Agg_LonPM180"
    e.griddap_initialize()

    e.constraints["time>="] = DATE_START
    e.constraints["time<="] = DATE_END
    e.constraints["latitude>="] = BBOX["lat_min"]
    e.constraints["latitude<="] = BBOX["lat_max"]
    e.constraints["longitude>="] = BBOX["lon_min"]
    e.constraints["longitude<="] = BBOX["lon_max"]

    print("Descargando...")
    ds = e.to_xarray()
    print(f"OK — shape: {ds[list(ds.data_vars)[0]].shape}")
    print(f"   variable: {list(ds.data_vars)}")
    print(f"   tiempo:   {ds.time.values[0]} -> {ds.time.values[-1]}")
    print(f"   lat:      {float(ds.latitude.min()):.2f} -> {float(ds.latitude.max()):.2f}")
    print(f"   lon:      {float(ds.longitude.min()):.2f} -> {float(ds.longitude.max()):.2f}")
    return ds


if __name__ == "__main__":
    try:
        test_chlorophyll()
    except Exception as e:
        print(f"ERROR clorofila: {e}")

    try:
        test_sst()
    except Exception as e:
        print(f"ERROR SST: {e}")
