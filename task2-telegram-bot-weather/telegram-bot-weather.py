import os
import json
import requests
import io
from datetime import timezone, timedelta, datetime

key = os.environ.get("OPEN_WEATHER_API_TOKEN")
weather_url = 'https://api.openweathermap.org/data/2.5/weather'
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
hpa_constant = 1.333
other_message_text = ("Я не могу ответить на такой тип сообщения. Но могу ответить на:\n"
"- Текстовое сообщение с названием населенного пункта.\n"
"- Голосовое сообщение с названием населенного пункта.\n"
"- Сообщение с геопозицией.")

FUNC_RESPONSE = {
    'statusCode': 200,
    'body': ''
}

def unix_to_moscow_time(unix_time):
    utc_time = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    moscow_tz = timezone(timedelta(hours=3))
    moscow_time = utc_time.astimezone(moscow_tz)
    return moscow_time.strftime('%H:%M')

def get_weather(params):
    response = requests.get(url=weather_url, params=params).json()
    desc = response['weather'][0]['description']
    temp = response['main']['temp']
    feels = response['main']['feels_like']
    pressure = response['main']['pressure']
    humidity = response['main']['humidity']
    visibility = response['visibility']
    wind_speed = response['wind']['speed']
    wind_dir = response['wind']['deg']
    sunrise = unix_to_moscow_time(response['sys']['sunrise'])
    sunset = unix_to_moscow_time(response['sys']['sunset'])

    directions = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ']
    wind_direction = directions[int((wind_dir + 22.5) // 45) % 8]

    weather_message = (
        f"{desc.capitalize()}.\n"
        f"Температура {temp} ℃, ощущается как {feels} ℃.\n"
        f"Атмосферное давление {pressure/hpa_constant} мм рт. ст.\n"
        f"Влажность {humidity} %.\n"
        f"Видимость {visibility} метров.\n"
        f"Ветер {wind_speed} м/с {wind_direction}.\n"
        f"Восход солнца {sunrise} МСК. Закат {sunset} МСК."
    )
    return weather_message

def send_message(text, message):
    """Отправка сообщения пользователю Telegram."""
    message_id = message['message_id']
    chat_id = message['chat']['id']
    reply_message = {'chat_id': chat_id,
                     'text': text,
                     'reply_to_message_id': message_id}

    # POST запросом отправим данные на сервер Telegram Bot API
    # Объект будет преобразован в JSON и отправиться как тело HTTP запроса.
    requests.post(url=f'{TELEGRAM_API_URL}/sendMessage', json=reply_message)

def send_voice(voice, message):
    """Отправка голосового сообщения пользователю Telegram."""

    message_id = message['message_id']
    chat_id = message['chat']['id']
    voice_file = io.BytesIO(voice)

    # https://core.telegram.org/bots/api#sendvoice
    # Сформируем URL для обращения к методу sendVoice из Telegram Bot API
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
    # Сформируем параметры для метода sendVoice из Telegram Bot API
    parameters = {"chat_id": chat_id}

    # POST запросом вызовем метод sendVoice Telegram Bot API.
    # Параметры передадим в виде URL query string HTTP-запроса.
    # Двоичные данные с голосовым сообщением передадим в теле HTTP-запроса
    # как multipart/form-data
    requests.post(url=url, data=parameters, files={"voice": voice_file})

def handler(event, context):
    if TELEGRAM_BOT_TOKEN is None:
        return FUNC_RESPONSE

    # Среда выполнения в аргументе event передает данные об HTTP запросе
    # преобразованные в словарь. В этом словаре по ключу body содержится тело
    # HTTP запроса. Сервер Telegram Bot API при использовании Webhook передает
    # в теле HTTP запроса объект Update в JSON формате. Мы этот объект
    # преобразуем в словарь.
    update = json.loads(event['body'])

    if 'message' not in update:
        return FUNC_RESPONSE

    # Если поле message присутствует, то извлекаем объект Message.
    message_in = update['message']

    if 'text' in message_in:
        w_params = {
            "q": message_in['text'],
            "appid": key,
            "lang": "ru",
            "units": "metric"
        }
        weather_message = get_weather(w_params)
        send_message(weather_message, message_in)
        return FUNC_RESPONSE

    if 'location' in message_in:
        location = message_in['location']
        w_params = {
            "lat": location['latitude'],
            "lon": location['longitude'],
            "appid": key,
            "lang": "ru",
            "units": "metric"
        }
        weather_message = get_weather(w_params)
        send_message(weather_message, message_in)
        return FUNC_RESPONSE

    if 'voice' in message_in:
        voice = message_in['voice']
        if voice['duration'] > 30:
            send_message("Голосовое сообщение должно быть меньше 30 секунд", message_in)
            return FUNC_RESPONSE
        
        audio_file_id = voice['file_id']
        tg_file_response = requests.post(url=f'{TELEGRAM_API_URL}/getFile', params={"file_id": audio_file_id})

        if "result" not in tg_file_response:
            send_message("Что-то пошло не так...", message_in)
            return FUNC_RESPONSE

        audio_file = tg_file_response['result']
        audio_file_path = audio_file['file_path']
        TG_BOT_API_FILE = f'https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{audio_file_path}'
        audio_file_content = requests.get(url=TG_BOT_API_FILE).content
        token = context.token['access_token']
        yc_auth = {"Authorization": f'Bearer{token}'}
        yc_url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        yc_response = requests.post(url = yc_url, headers = yc_auth, data = audio_file_content).json()

        if "result" not in yc_response:
            send_message("Не удалось распознать голосовое сообщение", message_in)
            return FUNC_RESPONSE

        w_params = {
            "q": yc_response['result'],
            "appid": key,
            "lang": "ru",
            "units": "metric"
        }

        weather_message = get_weather(w_params)
        # if not weather_message:
        #     send_message(f'Я не нашел населенный пункт "{yc_response["result"]}".', message_in)
        #     return FUNC_RESPONSE

        YC_TTS_API_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
        yc_tts_params = {
            "text": weather_message,
            "voice": "ermil",
            "emotion": "good"
        }

        yc_tts_resp = requests.post(url=YC_TTS_API_URL, data=yc_tts_params, headers=yc_auth)
    
        if not yc_tts_resp.ok:
            send_message("Не удалось синтезрировать голосовое сообщение", message_in)
            return FUNC_RESPONSE

        yc_tts_voice = yc_tts_resp.content
        send_voice(yc_tts_voice, message_in)
        return FUNC_RESPONSE
    
    send_message(other_message_text, message_in)
    return FUNC_RESPONSE