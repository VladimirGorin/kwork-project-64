from flask import Flask, request, jsonify
from telethon import TelegramClient, functions, errors
from config import TARGET_BOT, CHANNEL_USERNAME
import os
import json
import asyncio
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler('./logs/main.log'),
                        logging.StreamHandler()
                    ])
app = Flask(__name__)


class TelegramSessionManager:
    def __init__(self, sessions_dir, bad_sessions_file):
        self.sessions_dir = sessions_dir
        self.bad_sessions_file = bad_sessions_file

    def get_sessions(self):
        sessions = []
        for file in os.listdir(self.sessions_dir):
            if file.endswith('.session'):
                session_name = file.replace('.session', '')
                json_file = os.path.join(
                    self.sessions_dir, f'{session_name}.json')
                if os.path.exists(json_file):
                    sessions.append((session_name, json_file))
                else:
                    logging.error(f'JSON файл для сессии {
                                  session_name} не найден.')
        return sessions

    def load_api_credentials(self, json_file):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                app_id = data.get('app_id')
                app_hash = data.get('app_hash')
                if not app_id or not app_hash:
                    raise ValueError(
                        f'Недостаточно данных в файле {json_file}')
                return app_id, app_hash
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            logging.error(f'Ошибка при чтении {json_file}: {e}')
            return None, None

    def add_to_bad_sessions(self, session_name):
        with open(self.bad_sessions_file, 'a') as f:
            f.write(f'{session_name}\n')
        logging.info(f'Сессия {session_name} добавлена в черный список.')

    def remove_session(self, session_name):
        session_file = os.path.join(
            self.sessions_dir, f'{session_name}.session')
        json_file = os.path.join(self.sessions_dir, f'{session_name}.json')
        if os.path.exists(session_file):
            os.remove(session_file)
            logging.info(f'Сессия {session_name} удалена.')
        if os.path.exists(json_file):
            os.remove(json_file)
            logging.info(f'JSON файл для сессии {session_name} удален.')

    async def ensure_subscription(self, client):
        try:
            result = await client.get_entity(CHANNEL_USERNAME)
            if result.left:
                logging.info(f'Аккаунт не подписан на канал {
                             CHANNEL_USERNAME}, подписываемся.')
                await client(functions.channels.JoinChannelRequest(CHANNEL_USERNAME))
        except Exception as e:
            logging.error(f'Ошибка при подписке на канал {
                          CHANNEL_USERNAME}: {e}')
            return False
        return True

    async def sessions_validation(self, sessions):
        valid_sessions = []
        for session_name, json_file in sessions:
            try:
                session_file = os.path.join(self.sessions_dir, session_name)
                app_id, app_hash = self.load_api_credentials(json_file)
                if not app_id or not app_hash:
                    raise Exception("Не авторизован")
                client = TelegramClient(session_file, app_id, app_hash)
                await client.connect()
                if not await client.is_user_authorized():
                    raise Exception("Не авторизован")
                await client.disconnect()
                valid_sessions.append((session_name, json_file))
            except Exception:
                logging.error(f'Некорректная сессия {
                              session_name}. Удаляем сессию.')
                self.remove_session(session_name)
                self.add_to_bad_sessions(session_name)
        return valid_sessions

    async def send_messages_to_bot(self, ids, sessions):
        valid_sessions = await self.sessions_validation(sessions)
        if not valid_sessions:
            raise Exception("Нет валидных сессий")
        result = []
        while ids:
            print(len(ids), len(valid_sessions))

            valid_sessions_count = len(valid_sessions)
            if valid_sessions_count == 0:
                break

            ids_per_session = len(ids) // valid_sessions_count

            ids_per_session += 1 if ids_per_session * \
                valid_sessions_count < len(ids) else 0

            for session_name, json_file in valid_sessions:
                if not ids:
                    break
                try:
                    session_file = os.path.join(
                        self.sessions_dir, session_name)
                    app_id, app_hash = self.load_api_credentials(json_file)
                    if not app_id or not app_hash:
                        raise Exception("Не авторизован")
                    async with TelegramClient(session_file, app_id, app_hash) as client:
                        logging.info(f'Работаем с сессией {session_name}.')

                        if not await self.ensure_subscription(client):
                            self.remove_session(session_name)
                            self.add_to_bad_sessions(session_name)
                            continue

                        session_ids = ids[:ids_per_session]
                        ids = ids[ids_per_session:]

                        for message in session_ids:
                            message = message["id"]
                            logging.info(f"Отправляем ID: {
                                         message} через сессию {session_name}.")
                            await client.send_message(TARGET_BOT, message)
                            await asyncio.sleep(6)
                            async for response in client.iter_messages(TARGET_BOT, limit=1):
                                result.append(response.text)

                except errors.AuthKeyUnregisteredError:
                    logging.error(f'Необходимо ввести телефон или токен для сессии {
                                  session_name}. Удаляем сессию.')
                    self.remove_session(session_name)
                    self.add_to_bad_sessions(session_name)
                except (errors.SessionRevokedError, errors.PhoneCodeExpiredError, errors.FloodWaitError) as e:
                    logging.error(f'Ошибка с сессией {session_name}: {e}')
                    self.remove_session(session_name)
                    self.add_to_bad_sessions(session_name)
                except Exception as e:
                    logging.error(f'Неожиданная ошибка с сессией {
                                  session_name}: {e}')

        return result


session_manager = TelegramSessionManager('./sessions', './bad_sessions.txt')


@app.route('/api/get_info', methods=['POST'])
async def get_info():
    data = request.get_json()
    if 'ids' not in data:
        logging.error('Поле "ids" обязательно.')
        return jsonify({'error': 'Поле "ids" обязательно.'}), 400
    ids = data['ids']
    sessions = session_manager.get_sessions()
    if not sessions:
        logging.error('Нет доступных сессий.')
        return jsonify({'error': 'Нет доступных сессий.'}), 400
    result = await session_manager.send_messages_to_bot(ids, sessions)
    return jsonify({'result': result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
