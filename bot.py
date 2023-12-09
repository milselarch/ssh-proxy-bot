import asyncio
import logging
import subprocess

import telegram
import traceback
import textwrap
import yaml
import re

from result import Ok, Err, Result
from typing import List, Tuple

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    CommandHandler, ApplicationBuilder, ContextTypes
)


def track_errors(func):
    def caller(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(traceback.format_exc())
            raise e

    return caller


class SshProxyBot(object):
    def __init__(self, config_path='config.yml'):
        self.config_path = config_path

        self.bot = None
        self.app = None
        self.yaml_config = None
        self.process = None

        self.cmd = None
        self.remote_port = None
        self.server_ip = None

    @staticmethod
    def register_commands(
        dispatcher, commands_mapping, wrap_func=lambda func: func
    ):
        for command_name in commands_mapping:
            handler = commands_mapping[command_name]
            wrapped_handler = wrap_func(handler)
            dispatcher.add_handler(CommandHandler(
                command_name, wrapped_handler
            ))

    @track_errors
    async def name_id_handler(self, update, *args):
        """
        returns current user id and username
        """
        # when command /user_details is invoked
        user = update.message.from_user
        await update.message.reply_text(textwrap.dedent(f"""
            user id: {user['id']}
            username: {user['username']}
        """))

    @track_errors
    async def start_handler(
        self, update, _: ContextTypes.DEFAULT_TYPE
    ):
        await update.message.reply_text('Bot started')

    @track_errors
    async def launch_proxy(
        self, update, _: ContextTypes.DEFAULT_TYPE
    ):
        message = update.message
        user = update.message.from_user
        user_id = user['id']

        if user_id != self.yaml_config['telegram']['sudo_id']:
            await message.reply_text('ACCESS DENIED')
            return False

        if self.process is not None:
            await message.reply_text('SSH PROXY ALREADY RUNNING')
            return False

        self.process = subprocess.Popen(
            self.cmd, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True
        )

        await message.reply_text('ssh proxy started')
        return True

    @track_errors
    async def stop_proxy(
        self, update, _: ContextTypes.DEFAULT_TYPE
    ):
        message = update.message
        user = update.message.from_user
        user_id = user['id']

        if user_id != self.yaml_config['telegram']['sudo_id']:
            await message.reply_text('ACCESS DENIED')
            return False

        if self.process is None:
            await message.reply_text('SSH PROXY NOT RUNNING')
            return False

        self.process.kill()
        self.process = None
        await message.reply_text('ssh proxy terminated')
        return True

    @track_errors
    async def get_proxy_status(
        self, update, _: ContextTypes.DEFAULT_TYPE
    ):
        message = update.message
        user = update.message.from_user
        user_id = user['id']

        if user_id != self.yaml_config['telegram']['sudo_id']:
            await message.reply_text('ACCESS DENIED')
            return False

        if self.process is not None:
            await message.reply_text('ssh proxy running')
        else:
            await message.reply_text('ssh proxy not running')

    @track_errors
    async def read_proxy_stdout(
        self, update, _: ContextTypes.DEFAULT_TYPE
    ):
        message = update.message
        user = update.message.from_user
        user_id = user['id']

        if user_id != self.yaml_config['telegram']['sudo_id']:
            await message.reply_text('ACCESS DENIED')
            return False

        if self.process is None:
            await message.reply_text('SSH PROXY NOT RUNNING')
            return False

        lines = []
        while self.process.poll() is not None:
            line = self.process.stdout.readline()
            lines.append(line)
            await asyncio.sleep(0.1)

        stdout = '\n'.join(lines)
        await message.reply_text(f'STDOUT:\n{stdout}')

    def start_bot(self):
        with open(self.config_path, 'r') as config_file_obj:
            yaml_config = yaml.safe_load(config_file_obj)
            self.yaml_config = yaml_config
            tele_config = self.yaml_config['telegram']
            server_config = self.yaml_config['server']

            api_key = tele_config['bot_token']
            self.bot = telegram.Bot(token=api_key)
            self.remote_port = server_config['remote_port']
            self.server_ip = server_config['ip']

        self.app = ApplicationBuilder().token(api_key).build()
        self.cmd = (
            f'exec ssh -R {self.remote_port}:localhost:22 '
            f'milselarch@{self.server_ip}'
        )

        # on different commands - answer in Telegram
        self.register_commands(self.app, commands_mapping=self.kwargify(
            start=self.start_handler,
            user_details=self.name_id_handler,
            launch_proxy=self.launch_proxy,
            stop_proxy=self.stop_proxy,
            proxy_status=self.get_proxy_status,
            read_stdout=self.read_proxy_stdout
        ))

        # log all errors
        # dp.add_error_handler(error_logger)
        self.app.run_polling(allowed_updates=[Update.MESSAGE])

    @staticmethod
    def kwargify(**kwargs):
        return kwargs


if __name__ == '__main__':
    ssh_bot = SshProxyBot()
    ssh_bot.start_bot()
