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

import datetime
import json
import os
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request

RAIZ = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
# el servicio aparece con las dos grafias segun la fuente que mires
RUTAS = ["PreciosCarburantes", "PrecioCarburantes"]

# algunos servicios de la administracion cortan las peticiones que no
# parecen un navegador, asi que nos presentamos como uno
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://sedeaplicaciones.minetur.gob.es/",
    "Connection": "close",
}

PROVINCIAS = [p.strip() for p in os.environ.get("PROVINCIAS", "41").split(",") if p.strip()]
DESTINO = os.environ.get("DESTINO", "datos/gasolineras.json")

CARBURANTES = {
    "d":   ["precio gasoleo a"],
    "dp":  ["precio gasoleo premium"],
    "g95": ["precio gasolina 95 e5", "precio gasolina 95 e10",
            "precio gasolina 95 e5 premium"],
    "g98": ["precio gasolina 98 e5", "precio gasolina 98 e10"],
}

_NACIONAL = None  # cache del listado completo por si hace falta


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def descargar(url, intentos=3):
    """devuelve el JSON, o lanza RuntimeError con un mensaje que sirva de algo"""
    ultimo = ""
    for n in range(1, intentos + 1):
        try:
            req = urllib.request.Request(url, headers=CABECERAS)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=180,
                                        context=ssl.create_default_context()) as r:
                crudo = r.read()
            print("    recibidos %.0f KB en %.1f s" % (len(crudo) / 1024, time.time() - t0))
            for cod in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    return json.loads(crudo.decode(cod))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            ultimo = "respuesta ilegible, empieza por: %r" % crudo[:200]
        except urllib.error.HTTPError as e:
            cuerpo = ""
            try:
                cuerpo = e.read()[:200].decode("utf-8", "replace")
            except Exception:
                pass
            ultimo = "HTTP %s %s | %s" % (e.code, e.reason, cuerpo)
        except urllib.error.URLError as e:
            ultimo = "sin conexion: %s" % e.reason
        except Exception as e:
            ultimo = "%s: %s" % (type(e).__name__, e)

        print("    intento %d fallido -> %s" % (n, ultimo))
        if n < intentos:
            time.sleep(4 * n)
    raise RuntimeError(ultimo)


def lista_provincia(prov):
    """prueba las dos rutas del filtro y, si no, tira del listado nacional"""
    global _NACIONAL
    errores = []
    for ruta in RUTAS:
        url = RAIZ + ruta + "/EstacionesTerrestres/FiltroProvincia/" + prov
        print("  probando %s" % url)
        try:
            datos = descargar(url, intentos=2)
            lista = datos.get("ListaEESSPrecio")
            if lista:
                return datos.get("Fecha", ""), lista
            errores.append("%s: respuesta sin estaciones" % ruta)
        except RuntimeError as e:
            errores.append("%s: %s" % (ruta, e))

    print("  el filtro por provincia no ha funcionado")
    print("  voy con el listado nacional, que pesa bastante mas")
    if _NACIONAL is None:
        for ruta in RUTAS:
            try:
                _NACIONAL = descargar(RAIZ + ruta + "/EstacionesTerrestres/", intentos=2)
                break
            except RuntimeError as e:
                errores.append("nacional %s: %s" % (ruta, e))
    if not _NACIONAL:
        raise RuntimeError(" | ".join(errores))

    todas = _NACIONAL.get("ListaEESSPrecio") or []
    filtradas = [x for x in todas
                 if str(x.get("IDProvincia", "")).lstrip("0") == prov.lstrip("0")]
    return _NACIONAL.get("Fecha", ""), filtradas


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


def precios_recientes(limite_dias=3):
    """Si ya hay precios publicados y no son muy viejos, un corte puntual del
    Ministerio no debe tenir la ejecucion en rojo: la app sigue funcionando con
    los ultimos datos. Si llevan dias sin actualizarse, entonces si falla."""
    if not os.path.exists(DESTINO):
        print("No hay precios previos que conservar.", file=sys.stderr)
        return False
    try:
        with open(DESTINO, encoding="utf-8") as f:
            fecha = json.load(f).get("fecha", "")
        # formato del Ministerio: 27/07/2026 8:35:12
        d, m, a = fecha.split()[0].split("/")
        publicado = datetime.date(int(a), int(m), int(d))
        edad = (datetime.date.today() - publicado).days
    except Exception:
        print("No he podido leer la fecha de los precios previos.", file=sys.stderr)
        return False

    if edad <= limite_dias:
        print("AVISO: me quedo con los precios del %s (%d dias). "
              "La app sigue funcionando; si esto se repite varios dias, saltara en rojo."
              % (fecha, edad))
        return True
    print("Los precios publicados tienen %d dias, demasiados para ignorarlo." % edad,
          file=sys.stderr)
    return False


def procesar(lista):
    """convierte los registros del Ministerio en nuestro formato compacto"""
    salida = []
    nombre = ""
    for reg in lista:
        r = {norm(k): v for k, v in reg.items()}
        nombre = nombre or str(r.get("provincia", "")).strip().title()
        precios = {}
        for clave, alias in CARBURANTES.items():
            v = coge(r, alias)
            if v is not None:
                precios[clave] = v
        if not precios:
            continue
        lat = coord(r, "latitud")
        lon = coord(r, "longitud (wgs84)")
        if lon is None:
            lon = coord(r, "longitud")
        if lat is None or lon is None:
            continue
        salida.append({
            "r": str(r.get("rotulo", "")).strip().title(),
            "d": str(r.get("direccion", "")).strip().title(),
            "m": str(r.get("municipio", "")).strip(),
            "h": str(r.get("horario", "")).strip(),
            "lat": lat, "lon": lon, "p": precios,
        })
    salida.sort(key=lambda e: (e["m"], e["r"]))
    return nombre, salida


def escribir(ruta, obj):
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(ruta) / 1024


def main():
    carpeta = os.path.dirname(DESTINO) or "datos"
    indice = []
    fecha = ""
    primero = None

    for prov in PROVINCIAS:
        print("Provincia %s:" % prov)
        try:
            f, lista = lista_provincia(prov)
        except RuntimeError as e:
            print("El Ministerio no responde -> %s" % e, file=sys.stderr)
            return 0 if precios_recientes() else 1

        fecha = f or fecha
        nombre, estaciones = procesar(lista)
        print("  %d estaciones en bruto -> %d utiles" % (len(lista), len(estaciones)))
        if not estaciones:
            continue

        lats = [e["lat"] for e in estaciones]
        lons = [e["lon"] for e in estaciones]
        archivo = "gasolineras-%s.json" % prov
        datos = {"fecha": fecha, "provincia": nombre, "id": prov,
                 "n": len(estaciones), "e": estaciones}
        kb = escribir(os.path.join(carpeta, archivo), datos)
        print("  %s: %.0f KB" % (archivo, kb))

        if primero is None:
            primero = datos
        indice.append({
            "id": prov, "n": nombre or prov, "archivo": archivo,
            "est": len(estaciones),
            "lat": round(sum(lats) / len(lats), 4),
            "lon": round(sum(lons) / len(lons), 4),
            # margen de 0.15 grados para no dejar fuera los bordes
            "min": [round(min(lats) - 0.15, 4), round(min(lons) - 0.15, 4)],
            "max": [round(max(lats) + 0.15, 4), round(max(lons) + 0.15, 4)],
        })

    if not indice:
        print("ERROR: ninguna provincia ha dado estaciones", file=sys.stderr)
        return 1

    indice.sort(key=lambda p: p["n"])
    escribir(os.path.join(carpeta, "indice.json"),
             {"fecha": fecha, "provincias": indice})
    # copia de la primera provincia, para versiones antiguas de la app
    escribir(DESTINO, primero)

    print("Listo: %d provincias, %d estaciones, datos del %s"
          % (len(indice), sum(p["est"] for p in indice), fecha))
    return 0


if __name__ == "__main__":
    sys.exit(main())
