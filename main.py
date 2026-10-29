import os
import time
import warnings
import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.warnings import MissingPivotFunction

warnings.simplefilter("ignore", MissingPivotFunction)

URL = os.getenv("INFLUXDB_URL", "http://192.168.1.152:8086")
TOKEN = os.getenv("INFLUXDB_TOKEN", "gC_7P52MDhFcw3o-ZpfsHZ3jEEnHm12SCasXcf1fIjcueIORzY7_xyEYL1Dw_3BqtjdS0wNj35iZ5nIDezCA6w==")
ORG = os.getenv("INFLUXDB_ORG", "d72b1b37fb7052bd")
BUCKET = os.getenv("INFLUXDB_BUCKET", "finanzas")

STABLECOINS = {"USDT", "USDC", "DAI", "EUR"}

def obtener_foto_actual(client):
    """Obtiene los últimos balances de cada moneda."""
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

def obtener_historico_total(client, dias=30):
    """Consulta la suma histórica consolidada del portfolio por hora para cálculos estadísticos."""
    query_api = client.query_api()
    query = f'''
    from(bucket: "{BUCKET}")
      |> range(start: -{dias}d)
      |> filter(fn: (r) => r["_measurement"] == "patrimonio")
      |> filter(fn: (r) => r["_field"] == "valor_usdt")
      |> group(columns: ["_time"])
      |> sum()
      |> group()
      |> aggregateWindow(every: 1h, fn: last, createEmpty: false)
    '''
    return query_api.query_data_frame(query)

def calcular_metricas(df_actual, df_historico):
    if df_actual.empty or "valor_usdt" not in df_actual.columns:
        return None

    # --- 1. Foto actual: Total, Dominancias y Cash vs Risk-On ---
    resumen = df_actual[["activo", "valor_usdt"]].copy()
    total_portfolio = float(resumen["valor_usdt"].sum())
    resumen["dominancia_pct"] = (resumen["valor_usdt"] / total_portfolio) * 100

    es_cash = resumen["activo"].isin(STABLECOINS)
    valor_cash = float(resumen.loc[es_cash, "valor_usdt"].sum())
    valor_riskon = total_portfolio - valor_cash

    ratio_cash = (valor_cash / total_portfolio) * 100 if total_portfolio > 0 else 0.0
    ratio_riskon = 100.0 - ratio_cash

    # --- 2. Métricas de Riesgo y Volatilidad (Histórico) ---
    max_drawdown = 0.0
    current_drawdown = 0.0
    volatilidad_anual = 0.0
    sharpe_ratio = 0.0

    if not df_historico.empty and "_value" in df_historico.columns and len(df_historico) > 5:
        serie_total = df_historico["_value"]

        # Drawdown
        picos = serie_total.cummax()
        drawdowns = (serie_total - picos) / picos * 100.0
        max_drawdown = float(drawdowns.min())
        current_drawdown = float(drawdowns.iloc[-1])

        # Retornos diarios para Volatilidad y Sharpe
        df_historico["_time"] = pd.to_datetime(df_historico["_time"])
        df_diario = df_historico.set_index("_time")["_value"].resample("1D").last().dropna()

        if len(df_diario) >= 3:
            retornos = df_diario.pct_change().dropna()
            std_diaria = retornos.std()
            media_diaria = retornos.mean()

            if std_diaria > 0:
                volatilidad_anual = float(std_diaria * np.sqrt(365) * 100.0)
                # Tasa libre de riesgo simplificada a 0 (o staking base)
                sharpe_ratio = float((media_diaria * 365) / (std_diaria * np.sqrt(365)))

    metricas_resumen = {
        "total_usdt": total_portfolio,
        "valor_cash": valor_cash,
        "valor_riskon": valor_riskon,
        "ratio_cash_pct": ratio_cash,
        "ratio_riskon_pct": ratio_riskon,
        "drawdown_actual_pct": current_drawdown,
        "max_drawdown_pct": max_drawdown,
        "volatilidad_anual_pct": volatilidad_anual,
        "sharpe_ratio": sharpe_ratio
    }

    return resumen, metricas_resumen

def guardar_en_influx(client, resumen, metricas):
    write_api = client.write_api(write_options=SYNCHRONOUS)
    puntos = []

    # Punto global de resumen y métricas avanzadas
    p_total = Point("metricas_portfolio").tag("tipo", "resumen_total")
    for campo, valor in metricas.items():
        p_total.field(campo, float(valor))
    puntos.append(p_total)

    # Puntos desglosados por moneda
    for _, fila in resumen.iterrows():
        puntos.append(
            Point("metricas_portfolio")
            .tag("activo", str(fila["activo"]))
            .field("dominancia_pct", float(fila["dominancia_pct"]))
            .field("valor_usdt", float(fila["valor_usdt"]))
        )

    write_api.write(bucket=BUCKET, org=ORG, record=puntos)
    print(f"✅ [Éxito] Total: {metricas['total_usdt']:.2f} USDT | Cash: {metricas['ratio_cash_pct']:.1f}% | DD Actual: {metricas['drawdown_actual_pct']:.2f}% | Sharpe: {metricas['sharpe_ratio']:.2f}")

if __name__ == "__main__":
    INTERVALO_SEGUNDOS = 900
    print("🚀 Microservicio Python de Métricas Avanzadas iniciado...")

    while True:
        cliente = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
        try:
            df_act = obtener_foto_actual(cliente)
            df_hist = obtener_historico_total(cliente, dias=30)
            resultado = calcular_metricas(df_act, df_hist)
            if resultado:
                resumen_df, stats = resultado
                guardar_en_influx(cliente, resumen_df, stats)
        except Exception as e:
            print(f"❌ Error en la ejecución: {e}")
        finally:
            cliente.close()

        print(f"⏳ Esperando {INTERVALO_SEGUNDOS // 60} minutos...\n")
        time.sleep(INTERVALO_SEGUNDOS)