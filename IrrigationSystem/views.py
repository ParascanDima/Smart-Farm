# -*- coding: utf-8 -*-

from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from IrrigationSystem.weather import weatherlib
from IrrigationSystem.models import Wind, MeasureTime, GroundHumidity, Custom_User
from ipware.ip import get_ip
from django.views.decorators.csrf import csrf_exempt
import datetime
import os
import socket
import json
import threading
from webpush import send_user_notification

user = None

def TCP_Listner(connectionEntity):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	try:
		s.bind(('', connectionEntity.port))
	except:
		connectionEntity._activeConnection.shutdown(socket.SHUT_RD)
	s.listen(1)
	connectionEntity._activeConnection, (connectionEntity._ip_addr, wtf) = s.accept()

	connectionEntity._activeConnection.settimeout(60.0)
	connectionEntity._isConnected = True
	connectionEntity.checkConnectionThread = threading.Thread(target=gsmConnectionEntity.CheckConnection)
	connectionEntity.checkConnectionThread.daemon = True
	connectionEntity.checkConnectionThread.start()
	connectionEntity.listnerThread = None

class GsmCommand(object):

	def __init__(self):
		self.isWateringStarted = False
		self.isCollectingStarted = False
		self.commandSendTime = datetime.datetime.now()
		self.isActiveRequest = False

class GsmConnection(object):
	def __init__(self, port):
		self.port = port
		self._activeConnection = None
		self._ip_addr = None
		self._isConnected = False
		self.checkConnectionThread = None
		self.listnerThread = None

	def GetActiveConnection(self):
		return self._activeConnection

	def CheckConnection(self):
		global gsmStatus
		global user
		while True:
			if self._activeConnection is not None:
				try:
					data = self._activeConnection.recv(1024)
					if not data:
						pass
					elif "Collecting started" in data.decode("utf-8"):
						gsmStatus.isCollectingStarted = True
						gsmStatus.isActiveRequest = False
						payload = {'head': "Command result", 'body': "Collecting started"}
						send_user_notification(user=user, payload=payload, ttl=1000)
					elif "Watering started" in data.decode("utf-8"):
						gsmStatus.isCollectingStarted = True
						gsmStatus.isActiveRequest = False
						payload = {'head': "Command result", 'body': "Watering started"}
						send_user_notification(user=user, payload=payload, ttl=1000)
					else:
						print("WTF is going on?!")
				except:
					if gsmStatus.isActiveRequest:
						self.CloseActiveConnection()
						gsmStatus.isActiveRequest = False
			else:
				self.CloseActiveConnection()
				gsmStatus.isActiveRequest = False
				break

	def StartListnerThread(self):
		self.listnerThread = threading.Thread(target=TCP_Listner, args={self})
		self.listnerThread.daemon = True
		self.listnerThread.start()


	def StopListnerThread(self):
		self.listnerThread.stop()

	def CloseActiveConnection(self):
		self._activeConnection = None
		self._isConnected = False
		self._ip_addr = None
		self.checkConnectionThread = None

gsmConnectionEntity = GsmConnection(351)
gsmStatus = GsmCommand()

def index(request):
	global user
	webpush_settings = getattr(settings, 'WEBPUSH_SETTINGS', {})
	vapid_key = webpush_settings.get('VAPID_PUBLIC_KEY')
	user = request.user
	return render(request, 'IrrigationSystem/home.html', {"class_active" : "index", "user" : user, "vapid_key" : vapid_key})


def contact(request):
    return render(request, 'IrrigationSystem/basic.html',
                  {'content': [r'Номер мобильного(Moldcell): 079-22-98-87', r'Номер мобильного(Orange): 068-04-72-77', u'Почта: parascan.dima94@gmail.com'], "class_active" : "contact"})

def blog(request):
	return render(request, 'IrrigationSystem/basic.html',
                  {'content': ['Here will be schema of teritory sequences'], "class_active" : "blog"})

def weather(request, city = "Chisinau"):
	global weather_json

	weather_json = weatherlib.GetWeatherJSON(city)

	return render(request, 'IrrigationSystem/weather.html',
				  {'city' : weather_json.GetCity(),
				   'temperature': weather_json.GetTemperature(),
				   'humidity': weather_json.GetHumidity(),
				   'wind_speed': weather_json.GetWindSpeed(),
				   'wind_direction': weather_json.GetWindDirection(),})

def SocketSend(request, function):
	"""
	Functionality for sending
	"""
	global gsmConnectionEntity
	try:
		activeConnection = gsmConnectionEntity.GetActiveConnection()

		if function == "watering":
			message = b'Start watering\1\r\1\n'
			content = {'content': [u'Полив начанётся в течении одной минуты']}
		elif function == "collectdata":
			message = b'Start collecting data\1\r\1\n'
			content = {'content': [u'Сбор данных начанётся в течении одной минуты']}

	except Exception:
		return render(request, 'IrrigationSystem/basic.html', {'content': [u'Ошибка подключения к системе полива']})


	try:
		if gsmConnectionEntity._isConnected:
			status = activeConnection.sendall(message)
			if not status:
				gsmStatus.isActiveRequest = True
				gsmStatus.commandSendTime = datetime.datetime.now()
		else:
			content = {'content': [u'GSM is not connected']}
	except:
		content = {'content': [u'Error occures while sending the message']}


	return render(request, 'IrrigationSystem/basic.html', content)


@csrf_exempt
def DataTransfer(request):
	invalid_key = "Invalid Key"
	success = "Success"
	failed  = "Failed"
	if request.method == 'POST':
		json_string = "".join(map(chr, request.body))
		json_data = json.loads(json_string)
		try:
			wind_speed = Wind(speed = json_data["Wind_speed"])
			humidity = GroundHumidity(sensor = json_data["humidity"], averange=json_data["humidity"])
			measure_time = MeasureTime(date = datetime.datetime.now())
			measure_time.save()
			wind_speed.date = measure_time
			humidity.date = measure_time
			wind_speed.save()
			humidity.save()
		except KeyError:
			return HttpResponse(invalid_key)

		except Exception:
			return HttpResponse(failed)

		return HttpResponse(success)
	else:
	    return HttpResponse("Is not POST method")


def WindSpeedChartRender(request):
	return render(request, 'IrrigationSystem/chart.html', {"endpoint": "windspeedchart", "legend_label": u"скорость, м/с"})


def windspeedchart(request):
	wind_objects = list(Wind.objects.all().order_by('date__date'))
	data_set = [d.speed for d in wind_objects]
	labels = [d.date.date.strftime('%d-%m-%Y %H:%M:%S') for d in wind_objects]
	data = {
		'data_set': data_set,
		'labels': labels,
	}
	return JsonResponse(data)

def GroundHumidityChartRender(request):
	return render(request, 'IrrigationSystem/chart.html', {"endpoint": "groundhumiditychart", "legend_label": u"влажность"})

def groundhumiditychart(request):
	grhum_objects = list(GroundHumidity.objects.all().order_by('date__date'))
	data_set = [d.sensor for d in grhum_objects]
	labels = [d.date.date.strftime('%d-%m-%Y %H:%M:%S') for d in grhum_objects]
	data = {
		'data_set': data_set,
		'labels': labels,
	}
	return JsonResponse(data)

def SaveIP(request):
	global gsmConnectionEntity
	global subscribers

	ip = get_ip(request)
	if ip is not None:
		if gsmConnectionEntity.listnerThread is None:
			subscribers.append(ip)
			gsmConnectionEntity.StartListnerThread()

		return HttpResponse("Thanks, is OK")
	else:
		return HttpResponse("Oops, something wrong")

def ShowGSMIP(request):
	global gsmConnectionEntity

	if gsmConnectionEntity._ip_addr is not None:
		content = {'content':[gsmConnectionEntity._ip_addr]}
	else:
		content = {'content':[r'No connection']}

	return render(request, 'IrrigationSystem/basic.html', content)

