#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga los precios de carburante del Ministerio y deja un JSON pequeno
con las estaciones de las provincias elegidas.

Pensado para ejecutarse en GitHub Actions: el archivo resultante se publica
en el mismo sitio que la app, asi que el navegador se lo pide a su propio
dominio y no hay problema de CORS.

Variables de entorno:
  PROVINCIAS  ids separados por comas (41 = Sevilla). Por defecto "41".
  DESTINO     ruta del archivo de salida. Por defecto "datos/gasolineras.json".
"""

import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request

BASE = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes"
        "/PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/")

PROVINCIAS = [p.strip() for p in os.environ.get("PROVINCIAS", "41").split(",") if p.strip()]
DESTINO = os.environ.get("DESTINO", "datos/gasolineras.json")

# clave de salida -> nombres del Ministerio por orden de preferencia
CARBURANTES = {
    "d":   ["precio gasoleo a"],
    "dp":  ["precio gasoleo premium"],
    "g95": ["precio gasolina 95 e5", "precio gasolina 95 e10",
            "precio gasolina 95 e5 premium"],
    "g98": ["precio gasolina 98 e5", "precio gasolina 98 e10"],
}


def norm(s):
    """minusculas, sin acentos y sin espacios de mas"""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def pedir(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "garaje-app/1.0 (+https://github.com)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        crudo = r.read()
    for cod in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(crudo.decode(cod))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("no he podido interpretar la respuesta")


def numero(v):
    if v is None:
        return None
    v = str(v).strip().replace(",", ".")
    if not v:
        return None
    try:
        n = float(v)
    except ValueError:
        return None
    # descarta ceros y valores absurdos
    return round(n, 3) if 0.1 < n < 5 else None


def coord(reg, clave):
    """las longitudes espanolas son negativas, asi que van sin filtro de rango"""
    v = reg.get(clave)
    if v is None:
        return None
    try:
        return round(float(str(v).strip().replace(",", ".")), 5)
    except ValueError:
        return None


def coge(reg, claves):
    for c in claves:
        if c in reg:
            n = numero(reg[c])
            if n is not None:
                return n
    return None


def main():
    estaciones = []
    fecha = ""
    for prov in PROVINCIAS:
        url = BASE + prov
        print("Descargando provincia %s..." % prov)
        try:
            datos = pedir(url)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            print("  ERROR: %s" % e, file=sys.stderr)
            return 1

        fecha = datos.get("Fecha", fecha)
        lista = datos.get("ListaEESSPrecio") or []
        print("  %d estaciones en bruto" % len(lista))

        for reg in lista:
            # normalizamos las claves una vez por registro
            r = {norm(k): v for k, v in reg.items()}
            precios = {}
            for salida, claves in CARBURANTES.items():
                p = coge(r, claves)
                if p is not None:
                    precios[salida] = p
            if not precios:
                continue

            lat = coord(r, "latitud")
            lon = coord(r, "longitud (wgs84)")
            if lon is None:
                lon = coord(r, "longitud")
            if lat is None or lon is None:
                continue

            estaciones.append({
                "r": str(r.get("rotulo", "")).strip().title(),
                "d": str(r.get("direccion", "")).strip().title(),
                "m": str(r.get("municipio", "")).strip(),
                "h": str(r.get("horario", "")).strip(),
                "lat": lat,
                "lon": lon,
                "p": precios,
            })

    if not estaciones:
        print("No ha salido ninguna estacion, no toco el archivo", file=sys.stderr)
        return 1

    estaciones.sort(key=lambda e: (e["m"], e["r"]))
    salida = {
        "fecha": fecha,
        "provincias": PROVINCIAS,
        "n": len(estaciones),
        "e": estaciones,
    }

    carpeta = os.path.dirname(DESTINO)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(DESTINO, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))

    tam = os.path.getsize(DESTINO) / 1024
    print("Escrito %s: %d estaciones, %.0f KB, datos del %s"
          % (DESTINO, len(estaciones), tam, fecha))
    return 0


if __name__ == "__main__":
    sys.exit(main())
