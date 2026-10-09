"""
Benchmark de solo lectura del MCP de ERDDAP: las mismas preguntas contra dos
despliegues (el droplet viejo con Zarr + SQLite en disco, y el nuevo en ECS con
Zarr en S3 + catálogo en DynamoDB) para comparar tiempos y respuestas.

    python scripts/bench_mcp.py run --name nuevo --url https://mcp.chatmpa.ai/erddap \
        --header X-MCP-Api-Key --header-env MCP_API_KEY --out nuevo.json
    python scripts/bench_mcp.py compare viejo.json nuevo.json

Nunca llama a update_data: ninguna pregunta escribe en el store permanente. Las
preguntas on-demand (source != "auto") sí pueden dejar una entrada en el cache de
7 días del servidor la primera vez — es lo mismo que haría un usuario.

Tiempos: `base_s` es la mediana de varios `ping` JSON-RPC (red + auth + parseo
del servidor, sin tocar datos). Al comparar, a cada llamada se le resta la base
de su propio servidor para que la distancia no cuente como lentitud. Una sola
conexión HTTP keep-alive para toda la corrida, así el handshake TLS no entra.

Credenciales: solo por variable de entorno (--header-env), nunca en la línea de
comandos ni en el JSON de salida.
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone

import httpx

# Cabo Pulmo (BCS) y un recorte frente a Ensenada (VIIRS solo cubre lon <= -110).
CABO_PULMO = [-109.6, -109.3, 23.3, 23.6]
ENSENADA = [-117.0, -116.7, 31.6, 31.9]

# heavy=True se salta con --skip-heavy. reps = llamadas por pregunta (la 1ª es la
# "en frío"; las siguientes son lo que paga un usuario que repite o comparte la consulta).
PROBES = [
    # --- catálogo: SQLite en disco (viejo) vs DynamoDB (nuevo)
    dict(id="A1", group="catálogo", q="¿Qué datos hay guardados en el store?",
         tool="list_coverage", args={}, reps=3,
         shows="lee todo el catálogo (≈330 filas); SQLite local vs DynamoDB"),
    dict(id="A2", group="catálogo", q="¿Qué años de SST hay guardados?",
         tool="list_coverage", args={"variable": "sst"}, reps=3,
         shows="catálogo filtrado por variable"),
    # --- store permanente: Zarr en disco local vs Zarr en S3
    dict(id="B1", group="store", q="Clorofila promedio semanal del Pacífico mexicano en 2023",
         tool="get_data", args={"variable": "chlorophyll", "bbox": "pacific_mexico",
                                "date_range": ["2023-01-01", "2023-12-31"], "aggregate_spatial": True}, reps=3,
         shows="región completa, 1 año de chunks del store"),
    dict(id="B2", group="store", q="SST diaria promedio del Golfo de México en 2024",
         tool="get_data", args={"variable": "sst", "bbox": "gulf_mexico",
                                "date_range": ["2024-01-01", "2024-12-31"], "aggregate_spatial": True}, reps=3,
         shows="366 días de OISST; lectura de un año del store"),
    dict(id="B3", group="store", q="Clorofila en Cabo Pulmo, pixel por pixel, 2023",
         tool="get_data", args={"variable": "chlorophyll", "bbox": CABO_PULMO,
                                "date_range": ["2023-01-01", "2023-12-31"]}, reps=3,
         shows="sub-bbox: lee la región y recorta; respuesta pixel a pixel"),
    dict(id="B4", group="store", q="SST y anomalía diarias en Cabo Pulmo, 2024",
         tool="get_data", args={"variable": "sst", "bbox": CABO_PULMO, "date_range": ["2024-01-01", "2024-12-31"],
                                "sst_vars": ["sst", "anom"], "aggregate_spatial": True}, reps=3,
         shows="dos variables del mismo store, recorte chico"),
    dict(id="B5", group="store", q="SST diaria promedio del Pacífico mexicano 1995–2024 (30 años)",
         tool="get_data", args={"variable": "sst", "bbox": "pacific_mexico",
                                "date_range": ["1995-01-01", "2024-12-31"], "aggregate_spatial": True}, reps=2,
         heavy=True, shows="serie larga: ≈11,000 pasos de tiempo, lo más pesado que lee el store"),
    # --- on-demand: cache local en disco vs cache en S3 + registro en DynamoDB
    dict(id="C1", group="on-demand", q="SST de alta resolución (MUR 1 km) en Cabo Pulmo, 1–7 ago 2024",
         tool="get_data", args={"variable": "sst", "bbox": CABO_PULMO, "date_range": ["2024-08-01", "2024-08-07"],
                                "source": "mur_1km"}, reps=3,
         shows="1ª: ERDDAP si nadie la pidió antes; siguientes: cache de 7 días"),
    dict(id="C2", group="on-demand", q="Clorofila VIIRS 750 m frente a Ensenada, 1–10 jun 2024",
         tool="get_data", args={"variable": "chlorophyll", "bbox": ENSENADA, "date_range": ["2024-06-01", "2024-06-10"],
                                "source": "viirs_750m_npac"}, reps=3,
         shows="1ª: ERDDAP si nadie la pidió antes; siguientes: cache de 7 días"),
    # --- control: pasan directo a ERDDAP de NOAA, no tocan el store ni el cache
    dict(id="D1", group="control", q="¿Qué datasets de SST ofrece ERDDAP?",
         tool="list_datasets", args={"variable": "sst"}, reps=3,
         shows="búsqueda en ERDDAP de NOAA; no depende del store"),
    dict(id="D2", group="control", q="Metadatos del dataset MUR (jplMURSST41)",
         tool="get_dataset_info", args={"dataset_id": "jplMURSST41"}, reps=3,
         shows="info del dataset en ERDDAP de NOAA; no depende del store"),
    # --- honestidad: rangos que se salen de la cobertura
    dict(id="E1", group="honestidad", q="Clorofila del Pacífico mexicano, ene–sep 2026 (el store llega a mayo)",
         tool="get_data", args={"variable": "chlorophyll", "bbox": "pacific_mexico",
                                "date_range": ["2026-01-01", "2026-09-30"], "aggregate_spatial": True}, reps=1,
         shows="pide más de lo que hay: el nuevo avisa con meta.truncated; el viejo no"),
    dict(id="E2", group="honestidad", q="SST del Golfo de México 1975–1982 (OISST empieza en sep 1981)",
         tool="get_data", args={"variable": "sst", "bbox": "gulf_mexico",
                                "date_range": ["1975-01-01", "1982-12-31"], "aggregate_spatial": True}, reps=1,
         shows="rango que empieza antes de la cobertura: meta.truncated en el nuevo"),
]

SLOW_PROBE = "B5"            # la consulta lenta del test de concurrencia
FAST_TOOL = ("list_coverage", {"variable": "chlorophyll"})


class Mcp:
    """Cliente JSON-RPC mínimo sobre streamable-http, para medir sin capas extra."""

    def __init__(self, url: str, headers: dict, timeout: float):
        self.url = url
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **headers}
        self.http = httpx.Client(timeout=timeout, follow_redirects=True)
        self._id = 0
        self.session = None

    def rpc(self, method: str, params: dict | None = None, notify: bool = False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        h = dict(self.headers)
        if self.session:
            h["Mcp-Session-Id"] = self.session
        r = self.http.post(self.url, json=msg, headers=h)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        self.session = r.headers.get("mcp-session-id", self.session)
        if notify:
            return None
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            body = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    m = json.loads(line[5:])
                    if m.get("id") == msg["id"]:
                        body = m
            if body is None:
                raise RuntimeError("respuesta SSE sin el id pedido")
        else:
            body = r.json()
        if "error" in body:
            raise RuntimeError(f"JSON-RPC {body['error'].get('code')}: {body['error'].get('message')}")
        return body["result"]

    def initialize(self):
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "bench_mcp", "version": "1"}})
        self.rpc("notifications/initialized", notify=True)

    def close(self):
        self.http.close()


def summarize(result: dict) -> dict:
    """De un tools/call: ok, filas, aviso de truncado, origen y un chequeo del valor."""
    out = {"ok": not result.get("isError", False), "rows": None, "has_truncated_key": False,
           "truncated": None, "source": None, "check": None}
    text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    out["bytes"] = len(text.encode())
    try:
        payload = json.loads(text)
    except ValueError:
        if not out["ok"]:
            out["error"] = text[:300]
        return out
    if not isinstance(payload, dict):
        return out
    if "error" in payload:                     # p. ej. response_too_large
        out["ok"] = False
        out["error"] = str(payload.get("message") or payload["error"])[:300]
    meta = payload.get("meta") or {}
    data = payload.get("data")
    out["source"] = meta.get("source")
    if "truncated" in meta:
        out["has_truncated_key"] = True
        out["truncated"] = meta["truncated"]
    if "n_timesteps" in meta:
        out["rows"] = meta["n_timesteps"]
    elif "count" in meta:
        out["rows"] = meta["count"]
    elif isinstance(data, dict) and "times" in data:
        out["rows"] = len(data["times"])
    elif isinstance(data, list):
        out["rows"] = len(data)
    # Chequeo de que ambos servidores devuelven lo mismo: media de la primera serie.
    if isinstance(data, dict):
        series = next((v for k, v in data.items() if k not in ("time", "times", "lat", "lon")), None)
        flat = []
        stack = [series] if series is not None else []
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, (int, float)):
                flat.append(x)
        if flat:
            out["check"] = round(statistics.fmean(flat), 3)
    return out


def call_tool(c: Mcp, tool: str, args: dict) -> dict:
    t0 = time.perf_counter()
    try:
        res = c.rpc("tools/call", {"name": tool, "arguments": args})
        s = time.perf_counter() - t0
        return {"s": s, **summarize(res)}
    except Exception as e:  # noqa: BLE001 — se registra y sigue
        return {"s": time.perf_counter() - t0, "ok": False, "error": str(e)[:300]}


def measure_base(c: Mcp, n: int = 7) -> float:
    c.rpc("ping")  # calienta
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        c.rpc("ping")
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def fmt(s):
    if s is None:
        return "—"
    return f"{s * 1000:.0f} ms" if s < 1 else f"{s:.1f} s"


def cmd_run(a):
    headers = {}
    for name, env in zip(a.header or [], a.header_env or []):
        val = os.environ.get(env)
        if not val:
            sys.exit(f"Falta la variable de entorno {env} (para el header {name}).")
        headers[name] = val
    c = Mcp(a.url, headers, timeout=a.timeout)
    c.initialize()
    base = measure_base(c)
    print(f"[{a.name}] base de red (ping): {fmt(base)}", file=sys.stderr)

    probes = [p for p in PROBES if not (a.skip_heavy and p.get("heavy"))]
    if a.only:
        keep = set(a.only.split(","))
        probes = [p for p in probes if p["id"] in keep]
    out_probes = []
    for p in probes:
        calls = []
        for i in range(p["reps"]):
            r = call_tool(c, p["tool"], p["args"])
            calls.append(r)
            print(f"[{a.name}] {p['id']} #{i + 1}: {fmt(r['s'])}  ok={r['ok']} rows={r.get('rows')} "
                  f"src={r.get('source')} trunc={r.get('truncated')}"
                  + (f"  ERROR {r['error'][:120]}" if not r["ok"] else ""), file=sys.stderr)
        out_probes.append({k: p[k] for k in ("id", "group", "q", "tool", "args", "shows")} | {"calls": calls})

    extra = {}
    if not a.skip_extras:
        # Llamadas chicas seguidas: cuánto cuesta una consulta corta al catálogo.
        ts = [call_tool(c, *FAST_TOOL)["s"] for _ in range(20)]
        extra["catalog"] = {"tool": FAST_TOOL[0], "calls": len(ts), "first_s": ts[0],
                            "median_s": statistics.median(ts), "p95_s": sorted(ts)[int(0.95 * (len(ts) - 1))]}
        print(f"[{a.name}] catálogo x20: mediana {fmt(extra['catalog']['median_s'])}", file=sys.stderr)
        # Concurrencia: ¿una consulta lenta bloquea a las demás? Otra conexión,
        # lanzada 0.3 s después de la lenta.
        if not a.skip_heavy:
            slow = next(p for p in PROBES if p["id"] == SLOW_PROBE)
            res = {}

            def run_slow():
                c2 = Mcp(a.url, headers, timeout=a.timeout)
                c2.initialize()
                res["slow"] = call_tool(c2, slow["tool"], slow["args"])
                c2.close()

            c3 = Mcp(a.url, headers, timeout=a.timeout)
            c3.initialize()
            th = threading.Thread(target=run_slow)
            th.start()
            time.sleep(0.3)
            res["fast"] = call_tool(c3, *FAST_TOOL)
            th.join()
            c3.close()
            extra["concurrency"] = {"slow_probe": SLOW_PROBE, "fast_tool": FAST_TOOL[0],
                                    "slow_s": res["slow"]["s"], "slow_ok": res["slow"]["ok"],
                                    "fast_s": res["fast"]["s"], "fast_ok": res["fast"]["ok"]}
            print(f"[{a.name}] concurrencia: lenta {fmt(res['slow']['s'])}, rápida {fmt(res['fast']['s'])}",
                  file=sys.stderr)
    c.close()

    doc = {"name": a.name, "url": a.url, "when": datetime.now(timezone.utc).isoformat(),
           "base_s": base, "probes": out_probes, "extra": extra}
    with open(a.out, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"Escrito {a.out}", file=sys.stderr)


def net(p: dict, base: float):
    ok = [c["s"] for c in p["calls"] if c["ok"]]
    if not ok:
        return None, None
    first = max(ok[0] - base, 0)
    rest = max(statistics.median(ok[1:]) - base, 0) if len(ok) > 1 else None
    return first, rest


def cmd_compare(a):
    old, new = (json.load(open(f)) for f in (a.old, a.new))
    ob = {p["id"]: p for p in old["probes"]}
    print(f"base de red: {old['name']} {fmt(old['base_s'])} · {new['name']} {fmt(new['base_s'])}")
    print(f"{'id':4} {'viejo 1ª':>9} {'viejo 2ª+':>9} {'nuevo 1ª':>9} {'nuevo 2ª+':>9} {'mejora':>8}  filas v/n   valor v/n")
    for p in new["probes"]:
        o = ob.get(p["id"])
        nf, nr = net(p, new["base_s"])
        of, orr = net(o, old["base_s"]) if o else (None, None)
        nv = nr if nr is not None else nf
        ov = orr if orr is not None else of
        gain = f"{ov / max(nv, 0.05):.1f}×" if (nv is not None and ov is not None) else "—"
        last = lambda q, k: next((c.get(k) for c in reversed(q["calls"]) if c["ok"]), None) if q else None
        print(f"{p['id']:4} {fmt(of):>9} {fmt(orr):>9} {fmt(nf):>9} {fmt(nr):>9} {gain:>8}  "
              f"{last(o, 'rows')}/{last(p, 'rows'):<8} {last(o, 'check')}/{last(p, 'check')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="corre las preguntas contra un servidor")
    r.add_argument("--name", required=True)
    r.add_argument("--url", required=True)
    r.add_argument("--header", action="append", help="nombre del header de auth (repetible)")
    r.add_argument("--header-env", action="append", help="variable de entorno con su valor (mismo orden)")
    r.add_argument("--out", required=True)
    r.add_argument("--timeout", type=float, default=300)
    r.add_argument("--skip-heavy", action="store_true", help="sin B5 ni el test de concurrencia")
    r.add_argument("--skip-extras", action="store_true", help="sin catálogo x20 ni concurrencia")
    r.add_argument("--only", help="ids separados por coma, p. ej. A1,B2")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("compare", help="tabla lado a lado de dos corridas")
    c.add_argument("old")
    c.add_argument("new")
    c.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    if a.cmd == "run" and len(a.header or []) != len(a.header_env or []):
        ap.error("--header y --header-env van en pares")
    a.fn(a)


if __name__ == "__main__":
    main()
