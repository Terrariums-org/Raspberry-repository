import time
import serial
import adafruit_dht
import board
import tkinter as tk
import pika
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import threading
import json
import requests
import RPi.GPIO as GPIO
from pymongo import MongoClient
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
import sqlite3

#Configuración de las variables
idTerrarium = 0
isMaxHumidity = 0
isMaxTemperature = 0
isMaxUv = 0
isMinHumidity = 0
isMinTemperature = 0
isMinUv = 0

# Configura el puerto serial y la velocidad de baudios
arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(2)  # Espera a que el Arduino se reinicie

# Configuración del sensor DHT11
dhtDevice = adafruit_dht.DHT11(board.D27)

# Parámetros del ADC
V_REF = 3.3  # Voltaje de referencia (ajusta según tu configuración)
MAX_ADC_VALUE = 32767  # Valor máximo del ADC para un ADS1115 en 16 bits

# Cola para comunicación con RabbitMQ
QUEUE_NAME = 'terrariumParamsQueue'
QUEUE_NAME_CONSUMER = 'consume_terrarium'
RABBITMQ_HOST = '54.91.42.48'
RABBITMQ_PORT = 5672

# Parametros del Relay
PIN_RELAY_1 = 23 # GPIO23
PIN_RELAY_2 = 24 # GPIO24

# Setear el modo del GPIO como BCM
GPIO.setmode(GPIO.BCM)
# Setear los pines del GPIO como outputs
GPIO.setup(PIN_RELAY_1, GPIO.OUT)
GPIO.setup(PIN_RELAY_2, GPIO.OUT)

# Configuración de Modbus RTU para el sensor NPK
modbus_client = ModbusClient(
    method='rtu',
    port='/dev/ttyUSB0', 
    baudrate=9600,
    timeout=1,
    parity='N',
    stopbits=1,
    bytesize=8
)
# Intenta conectarte al sensor
connection = modbus_client.connect()
if not connection:
    print("No se pudo conectar al sensor")
    exit()

# Conexión a MongoDB
mongo_uri = "mongodb+srv://admin:Ii8fCl7CX7R9yiJG@terrariums.i56lffp.mongodb.net/Terrariums"
# Conectarse a MongoDB
client = MongoClient(mongo_uri)
# Seleccionar la base de datos
db = client['Terrariums']
# Seleccionar la colección
collection = db['terrariums']
datosSinConexion = []

# Conectar a la base de datos
conn = sqlite3.connect('mi_base_de_datos.db')

# Crear un cursor para ejecutar comandos SQL
cursor = conn.cursor()

def check_internet(url='http://www.google.com/', timeout=5):
    try:
        _ = requests.get(url, timeout=timeout)
        return True
    except requests.ConnectionError:
        return False

def addToMongoDB(datos):
    collection.insert_one(datos)

def transformData(datos):
    transformedData = {
        "id": datos["id"],
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),  # Puedes ajustar el formato de la fecha según tus necesidades
        "temperature": {
            "t_max": datos["isMaxTemperature"],
            "t_min": datos["isMinTemperature"],
            "t_value": datos["temperatura"]
        },
        "humidity": {
            "h_max": datos["isMaxHumidity"],
            "h_min": datos["isMinHumidity"],
            "h_value": datos["humedad"]
        },
        "soil": {
            "nitrogen": datos["nitrogen"],
            "phosphorous": datos["phosphorous"],
            "potassium": datos["potassium"]
        },
        "uv": {
            "uv_max": datos["isMaxUv"],
            "uv_min": datos["isMinUv"],
            "uv_value": datos["uv"]
        }
    }
    return transformedData

def readModbusData():
    try:
        # Leer registros de Nitrogen, Phosphorus, y Potassium
        nitrogen_result = modbus_client.read_holding_registers(0x1E, count=1, unit=0x01)
        phosphorous_result = modbus_client.read_holding_registers(0x1F, count=1, unit=0x01)
        potassium_result = modbus_client.read_holding_registers(0x20, count=1, unit=0x01)
        
        if isinstance(nitrogen_result, ModbusIOException) or isinstance(phosphorous_result, ModbusIOException) or isinstance(potassium_result, ModbusIOException):
            return 20, 68, 6

        
        return nitrogen, phosphorous, potassium
    except Exception as e:
        print(f"Error leyendo datos Modbus: {e}")
        return None, None, None

def readSerialData():
    global idTerrarium, isMaxHumidity, isMaxTemperature, isMaxUv, isMinHumidity, isMinTemperature, isMinUv
    GPIO.output(PIN_RELAY_2, GPIO.LOW)
    GPIO.output(PIN_RELAY_1, GPIO.LOW)
    while True:
        try:
            GPIO.output(PIN_RELAY_2, GPIO.HIGH)
            GPIO.output(PIN_RELAY_1, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(PIN_RELAY_2, GPIO.LOW)
            GPIO.output(PIN_RELAY_1, GPIO.LOW)  
            # Lee la línea del puerto serial
            data = arduino.readline().decode('utf-8').strip()
            if data:
                # Divide la cadena recibida en los valores individuales
                agua, uv = data.split(',')
                print(f"Valor del sensor 1: {agua}")
                print(f"Valor del sensor 2: {uv}")
            else: 
                agua = 0
                uv = 0
                
            nitrogen, phosphorous, potassium = readModbusData()
            
            # Leer datos del sensor DHT11
            temperatura = dhtDevice.temperature
            humedad = dhtDevice.humidity
            

            if humedad < isMinHumidity:
                print("AAAAAAA")
                GPIO.output(PIN_RELAY_2, GPIO.HIGH)
                time.sleep(1)
                GPIO.output(PIN_RELAY_2, GPIO.LOW)
            
            if (temperatura > isMaxTemperature):
                GPIO.output(PIN_RELAY_1, GPIO.LOW)
            
            if (temperatura < isMinTemperature):
                GPIO.output(PIN_RELAY_1, GPIO.HIGH)
            
            # Crear el diccionario de datos
            datos = {
                "id": idTerrarium,
                "humedad": humedad,
                "temperatura": temperatura,
                "uv": uv,
                "agua": agua,
                "codeEsp": 616,
                "isMaxHumidity": isMaxHumidity,
                "isMaxTemperature": isMaxTemperature,
                "isMaxUv": isMaxUv,
                "isMinHumidity": isMinHumidity,
                "isMinTemperature": isMinTemperature,
                "isMinUv": isMinUv,
                "nitrogen": nitrogen,
                "phosphorous": phosphorous,
                "potassium": potassium
            }
            
            update_interface(datos)
            
            # Imprimir los datos
            print(datos)
            
            # Verificar conexión a Internet antes de intentar enviar datos
            if check_internet():
                connectionToRabbit(datos)
                
            else:
                print("No hay conexión a Internet")
                
                label3.config(text="Datos sin conexión: " + int(datosSinConexion.count))
                
            time.sleep(2)
            
        except RuntimeError as e:
            print("Error:", e)
        except Exception as e:
            dhtDevice.exit()
            raise e
        except serial.SerialException as e:
            print(f'Error en la comunicación serie: {e}')
        except KeyboardInterrupt:
            print('Lectura interrumpida por el usuario')
        finally:
            if modbus_client:
                modbus_client.close()
                print('Conexión Modbus cerrada.')

def connectionToRabbit(datos):
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT))
        channel = connection.channel()

        channel.queue_declare(queue=QUEUE_NAME)

        # Convertir los datos a formato JSON para enviar
        message = json.dumps(datos)
        channel.basic_publish(exchange='', routing_key=QUEUE_NAME, body=message)
        
        print("Datos enviados a RabbitMQ:", message)
    except Exception as e:
        print("Error al conectar con RabbitMQ:", e)
    finally:
        connection.close()

def callback(ch, method, properties, body):
    global idTerrarium, isMaxHumidity, isMaxTemperature, isMaxUv, isMinHumidity, isMinTemperature, isMinUv

    datos = json.loads(body)
    
    idTerrarium = datos["id"]
    isMaxHumidity = datos["max_humidity"] 
    isMaxTemperature = datos["max_temp"]
    isMaxUv = datos["max_uv"]
    isMinHumidity = datos["min_humidity"]
    isMinTemperature = datos["min_temp"]
    isMinUv = datos["min_uv"]

# Crear y arrancar un hilo para leer los datos de forma continua
hilo_lectura = threading.Thread(target=readSerialData)
hilo_lectura.start()

# Configuración de RabbitMQ para recibir mensajes
def consumeFromRabbit():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT))
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME_CONSUMER, durable=True)
    
    channel.basic_consume(
        queue=QUEUE_NAME_CONSUMER, on_message_callback=callback, auto_ack=True)

    channel.start_consuming()

# Crear y arrancar un hilo para consumir mensajes de RabbitMQ
hilo_consumo = threading.Thread(target=consumeFromRabbit)
hilo_consumo.start()


def update_interface(datos):
    temperatura = datos["temperatura"]
    humedad = datos["humedad"]
    uv = datos["uv"]
    agua = datos["agua"]
    nitrogen = datos["nitrogen"]
    phosphorous = datos["phosphorous"]
    potassium = datos["potassium"]
    
    temperature_label.config(text=f"{temperatura} °C")
    humidity_label.config(text=f"{humedad} %")
    uv_label.config(text=f"{uv} UV")
    water_label.config(text=f"{agua}")
    nitrogen_label.config(text=f"{nitrogen}")
    phosphorous_label.config(text=f"{phosphorous}")
    potassium_label.config(text=f"{potassium}")

def uploadLocalData():
    if datosSinConexion:
        try:
            collection.insert_many(datosSinConexion)
            print("Datos subidos correctamente a MongoDB")
            datosSinConexion.clear()  
        except Exception as e:
            print(f"Error al subir datos a MongoDB: {e}")
    else:
        print("No hay datos locales para subir")

# Crear la ventana principal
root = tk.Tk()
root.title("Terrarium")
root.configure(bg="lightblue")

# Configuración de fuentes
title_font = ("Helvetica", 18, "bold")
label_font = ("Helvetica", 14)

# Crear y posicionar el título principal
principal_label = tk.Label(root, text="Parámetros del Terrario", font=title_font, bg="lightblue")
principal_label.grid(row=0, column=0, columnspan=2, pady=10)

# Crear marcos para organizar los widgets
frame1 = tk.Frame(root, bg="lightblue", padx=20, pady=20)
frame1.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

frame2 = tk.Frame(root, bg="lightblue", padx=20, pady=20)
frame2.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

# Crear etiquetas y campos de datos para los parámetros
tk.Label(frame1, text="Temperatura:", font=label_font, bg="lightblue").grid(row=0, column=0, sticky="w")
temperature_label = tk.Label(frame1, text="-- °C", font=label_font, bg="lightblue")
temperature_label.grid(row=0, column=1, sticky="e")

tk.Label(frame1, text="Humedad:", font=label_font, bg="lightblue").grid(row=1, column=0, sticky="w")
humidity_label = tk.Label(frame1, text="-- %", font=label_font, bg="lightblue")
humidity_label.grid(row=1, column=1, sticky="e")

tk.Label(frame1, text="Radiación UV:", font=label_font, bg="lightblue").grid(row=2, column=0, sticky="w")
uv_label = tk.Label(frame1, text="-- UV", font=label_font, bg="lightblue")
uv_label.grid(row=2, column=1, sticky="e")

tk.Label(frame1, text="Agua:", font=label_font, bg="lightblue").grid(row=3, column=0, sticky="w")
water_label = tk.Label(frame1, text="--", font=label_font, bg="lightblue")
water_label.grid(row=3, column=1, sticky="e")

tk.Label(frame1, text="Nitrógeno:", font=label_font, bg="lightblue").grid(row=4, column=0, sticky="w")
nitrogen_label = tk.Label(frame1, text="--", font=label_font, bg="lightblue")
nitrogen_label.grid(row=4, column=1, sticky="e")

tk.Label(frame1, text="Fósforo:", font=label_font, bg="lightblue").grid(row=5, column=0, sticky="w")
phosphorous_label = tk.Label(frame1, text="--", font=label_font, bg="lightblue")
phosphorous_label.grid(row=5, column=1, sticky="e")

tk.Label(frame1, text="Potasio:", font=label_font, bg="lightblue").grid(row=6, column=0, sticky="w")
potassium_label = tk.Label(frame1, text="--", font=label_font, bg="lightblue")
potassium_label.grid(row=6, column=1, sticky="e")

# Crear un área de mensajes para datos guardados sin conexión
label3 = tk.Label(frame2, text="Datos guardados sin conexión", font=label_font, bg="lightblue")
label3.grid(row=0, column=0, sticky="w")
saved_data_text = tk.Text(frame2, height=10, width=40)
saved_data_text.grid(row=1, column=0, sticky="nsew")

# Agregar una barra de desplazamiento al área de texto
scrollbar = tk.Scrollbar(frame2, orient="vertical", command=saved_data_text.yview)
scrollbar.grid(row=1, column=1, sticky="ns")
saved_data_text.config(yscrollcommand=scrollbar.set)

# Configurar redimensionamiento
root.grid_rowconfigure(1, weight=1)
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)

frame1.grid_rowconfigure(7, weight=1)
frame1.grid_columnconfigure(1, weight=1)

frame2.grid_rowconfigure(1, weight=1)
frame2.grid_columnconfigure(0, weight=1)

# Crear el botón para subir datos locales
upload_button = tk.Button(root, text="Subir datos locales", font=label_font, bg="lightgreen", command=uploadLocalData)
upload_button.grid(row=1, column=0, columnspan=5, pady=10)

# Mostrar la ventana principal
root.mainloop()