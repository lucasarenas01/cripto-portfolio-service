import os
import warnings
import time
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.warnings import MissingPivotFunction
import pandas as pd

warnings.simplefilter("ignore", MissingPivotFunction)

# Configuración de variables de entorno
URL = os.getenv("INFLUXDB_URL", "http://192.168.1.152:8086")
TOKEN = os.getenv("INFLUXDB_TOKEN", "gC_7P52MDhFcw3o-ZpfsHZ3jEEnHm12SCasXcf1fIjcueIORzY7_xyEYL1Dw_3BqtjdS0wNj35iZ5nIDezCA6w==")
ORG = os.getenv("INFLUXDB_ORG", "d72b1b37fb7052bd")
BUCKET = os.getenv("INFLUXDB_BUCKET", "finanzas")

def obtener_datos(client):
    query_api = client.query_api()
    query = f'''
    from(bucket: "{BUCKET}")
      |> range(start: -7d)
      |> filter(fn: (r) => r["_measurement"] == "patrimonio")
      |> filter(fn: (r) => r["_field"] == "valor_usdt")
      |> last()
      |> pivot(rowKey:["_time", "activo"], columnKey: ["_field"], valueColumn: "_value")
    '''
    return query_api.query_data_frame(query)

def procesar_y_guardar(client, df):
    if df.empty or "valor_usdt" not in df.columns:
        print("⚠️ No hay datos suficientes para calcular.")
        return

    # 1. Cálculos de métricas con Pandas
    resumen = df[["activo", "valor_usdt"]].copy()
    total_portfolio = resumen["valor_usdt"].sum()
    resumen["dominancia_%"] = (resumen["valor_usdt"] / total_portfolio) * 100

    # 2. Preparar los puntos para InfluxDB
    write_api = client.write_api(write_options=SYNCHRONOUS)
    puntos = []

    # Punto 1: Total Portfolio
    puntos.append(
        Point("metricas_portfolio")
        .tag("tipo", "resumen_total")
        .field("total_usdt", float(total_portfolio))
    )

    # Puntos 2: Dominancia por activo
    for _, fila in resumen.iterrows():
        puntos.append(
            Point("metricas_portfolio")
            .tag("activo", str(fila["activo"]))
            .field("dominancia_pct", float(fila["dominancia_%"]))
            .field("valor_usdt", float(fila["valor_usdt"]))
        )

    # 3. Escritura física en InfluxDB
    write_api.write(bucket=BUCKET, org=ORG, record=puntos)
    print(f"\n✅ [Éxito] Métricas guardadas en InfluxDB:")
    print(f"   -> Total Portfolio: {total_portfolio:.2f} USDT")
    print(f"   -> Activos procesados: {len(resumen)}")

if __name__ == "__main__":
    INTERVALO_SEGUNDOS = 900  # Se ejecuta cada 15 minutos

    print("🚀 Microservicio Python de Métricas iniciado...")
    while True:
        cliente = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
        try:
            df_datos = obtener_datos(cliente)
            procesar_y_guardar(cliente, df_datos)
        except Exception as e:
            print(f"❌ Error en la ejecución: {e}")
        finally:
            cliente.close()
            
        print(f"⏳ Esperando {INTERVALO_SEGUNDOS // 60} minutos para el siguiente cálculo...\n")
        time.sleep(INTERVALO_SEGUNDOS)